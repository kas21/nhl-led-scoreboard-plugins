"""Utility classes and helpers for the NFL board."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional

import debug
import requests
from PIL import Image


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ESPN ISO timestamps (that typically end with ``Z``)."""
    if not value:
        return None
    try:
        # ESPN dates are UTC with "Z". ``fromisoformat`` needs ``+00:00``.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        debug.error(f"NFL board: could not parse date value '{value}'")
    return None


def _safe_int(value: Optional[str]) -> Optional[int]:
    """Convert ESPN score strings to integers."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick_logo_url(logos: Optional[Iterable[dict]]) -> Optional[str]:
    """Return the best looking logo URL available."""
    if not logos:
        return None

    chosen = None
    for logo in logos:
        rel = logo.get("rel") or []
        if "scoreboard" in rel:
            return logo.get("href")
        if chosen is None:
            chosen = logo.get("href")
    return chosen


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    # Strip leading '#' if present
    hex_color = hex_color.lstrip('#')
    # Split into pairs and convert each to int
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


@dataclass
class NFLTeam:
    """Structured representation of an NFL franchise."""

    id: str
    display_name: str
    abbreviation: str
    location: str
    name: str
    color_primary: str
    color_secondary: str
    record_summary: str
    record_comment: Optional[str]
    logo_url: Optional[str] = None
    logo_path: Optional[Path] = None

    @property
    def logo_filename(self) -> str:
        return f"{self.abbreviation.lower()}.png"


@dataclass
class NFLGame:
    """Game information with home and away team objects."""

    event_id: str
    date: Optional[datetime]
    home_team: NFLTeam
    away_team: NFLTeam
    status_state: str
    status_detail: str
    is_completed: bool
    is_live: bool
    home_score: Optional[int]
    away_score: Optional[int]
    venue: Optional[str] = None

    def result_token(self, team_id: str) -> Optional[str]:
        """Return ``W``/``L``/``T`` for the specified team once the contest is final."""
        if not self.is_completed or self.home_score is None or self.away_score is None:
            return None

        if self.home_team.id == team_id:
            our_score = self.home_score
            opponent_score = self.away_score
        elif self.away_team.id == team_id:
            our_score = self.away_score
            opponent_score = self.home_score
        else:
            return None

        if our_score > opponent_score:
            return "W"
        if our_score < opponent_score:
            return "L"
        return "T"

    def get_opponent(self, team_id: str) -> Optional[NFLTeam]:
        """Get the opponent team for the specified team."""
        if self.home_team.id == team_id:
            return self.away_team
        elif self.away_team.id == team_id:
            return self.home_team
        return None

    def is_home_team(self, team_id: str) -> bool:
        """Check if the specified team is playing at home."""
        return self.home_team.id == team_id

    def get_team_score(self, team_id: str) -> Optional[int]:
        """Get the score for the specified team."""
        if self.home_team.id == team_id:
            return self.home_score
        elif self.away_team.id == team_id:
            return self.away_score
        return None

    def get_opponent_score(self, team_id: str) -> Optional[int]:
        """Get the opponent's score for the specified team."""
        if self.home_team.id == team_id:
            return self.away_score
        elif self.away_team.id == team_id:
            return self.home_score
        return None


class NFLApiClient:
    """Thin wrapper around ESPN's public NFL endpoints."""

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"

    def __init__(self, logo_dir: Path, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.logo_dir = logo_dir
        self.logo_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------------
    # Public API

    def fetch_team_payload(self, team_id: str) -> tuple[NFLTeam, list[NFLGame]]:
        """Fetch team metadata plus their schedule."""

        team_json = self._get_json(f"teams/{team_id}")
        schedule_json = self._get_json(f"teams/{team_id}/schedule")
        all_teams_json = self._get_json("teams")

        team = self._parse_team(team_json)
        teams_lookup = self._build_teams_lookup(all_teams_json)
        games = self._parse_schedule(schedule_json, team_id, teams_lookup)

        if team.logo_url:
            team.logo_path = self._ensure_logo(team.abbreviation, team.logo_url)

        # Ensure logos for all teams in games
        for game in games:
            if game.home_team.logo_url and not game.home_team.logo_path:
                game.home_team.logo_path = self._ensure_logo(game.home_team.abbreviation, game.home_team.logo_url)
            if game.away_team.logo_url and not game.away_team.logo_path:
                game.away_team.logo_path = self._ensure_logo(game.away_team.abbreviation, game.away_team.logo_url)

        return team, games

    # ------------------------------------------------------------------
    # Internal helpers

    def _get_json(self, path: str) -> dict:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        debug.info(f"NFL board: fetching {url}")
        response = self.session.get(url, timeout=10)
        response.raise_for_status()
        return response.json()

    def _ensure_logo(self, abbreviation: str, url: str) -> Optional[Path]:
        """Download and cache the team logo as a 64px PNG."""
        try:
            destination = self.logo_dir / f"{abbreviation.lower()}.png"
            if destination.exists():
                return destination

            debug.info(f"NFL board: caching logo for {abbreviation} from {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            image = Image.open(BytesIO(response.content)).convert("RGBA")
            # Trim Transparency
            bbox = image.getbbox()
            image = image.crop(bbox)
            # Keep aspect ratio but ensure the longest edge is 64px.
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
            if resampling is None:
                resampling = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
            image.thumbnail((64, 64), resampling)
            image.save(destination, format="PNG")
            return destination
        except Exception as exc:  # pragma: no cover - defensive logging
            debug.error(f"NFL board: failed to cache logo {url}: {exc}")
        return None

    def _parse_team(self, payload: dict) -> NFLTeam:
        team_info = payload.get("team", {})
        record_summary = ""
        record_comment = team_info.get("standingSummary")

        record = team_info.get("record", {})
        for item in record.get("items", []):
            summary = item.get("summary")
            if summary:
                record_summary = summary
                break

        logos = team_info.get("logos") or []
        logo_url = _pick_logo_url(logos)

        color_primary=team_info.get("color") or ""
        color_secondary=team_info.get("alternateColor") or ""

        color_primary = _hex_to_rgb(color_primary)
        color_secondary = _hex_to_rgb(color_secondary)

        return NFLTeam(
            id=str(team_info.get("id")),
            display_name=team_info.get("displayName") or team_info.get("name") or "",
            abbreviation=team_info.get("abbreviation") or "",
            location=team_info.get("location") or "",
            name=team_info.get("name") or "",
            color_primary=color_primary,
            color_secondary=color_secondary,
            record_summary=record_summary,
            record_comment=record_comment,
            logo_url=logo_url,
        )

    def _build_teams_lookup(self, payload: dict) -> dict[str, NFLTeam]:
        """Build a lookup dictionary of all NFL teams."""
        teams_lookup = {}
        if "sports" in payload:
            teams = payload["sports"][0]["leagues"][0]["teams"]
            for team_data in teams:
                team = self._parse_team_from_teams_endpoint(team_data["team"])
                teams_lookup[team.id] = team
        return teams_lookup

    def _parse_schedule(self, payload: dict, team_id: str, teams_lookup: dict[str, NFLTeam]) -> list[NFLGame]:
        events = payload.get("events", [])
        games: list[NFLGame] = []
        team_id = str(team_id)

        for event in events:
            game = self._parse_game(event, team_id, teams_lookup)
            if game:
                games.append(game)
        return games

    def _parse_team_from_teams_endpoint(self, team_info: dict) -> NFLTeam:
        """Parse team data from the teams endpoint (different structure than team-specific endpoint)."""
        record_summary = ""
        record_comment = team_info.get("standingSummary")

        record = team_info.get("record", {})
        for item in record.get("items", []):
            summary = item.get("summary")
            if summary:
                record_summary = summary
                break

        logos = team_info.get("logos") or []
        logo_url = _pick_logo_url(logos)

        color_primary = team_info.get("color") or ""
        color_secondary = team_info.get("alternateColor") or ""

        if color_primary:
            color_primary = _hex_to_rgb(color_primary)
        if color_secondary:
            color_secondary = _hex_to_rgb(color_secondary)

        return NFLTeam(
            id=str(team_info.get("id")),
            display_name=team_info.get("displayName") or team_info.get("name") or "",
            abbreviation=team_info.get("abbreviation") or "",
            location=team_info.get("location") or "",
            name=team_info.get("name") or "",
            color_primary=color_primary,
            color_secondary=color_secondary,
            record_summary=record_summary,
            record_comment=record_comment,
            logo_url=logo_url,
        )

    def _parse_game(self, event: dict, team_id: str, teams_lookup: dict[str, NFLTeam]) -> Optional[NFLGame]:
        competitions = event.get("competitions", [])
        competition = competitions[0] if competitions else {}

        competitors = competition.get("competitors", [])
        home_competitor = None
        away_competitor = None

        for comp in competitors:
            if comp.get("homeAway") == "home":
                home_competitor = comp
            else:
                away_competitor = comp

        if home_competitor is None or away_competitor is None:
            return None

        home_team_id = str(home_competitor.get("team", {}).get("id"))
        away_team_id = str(away_competitor.get("team", {}).get("id"))

        # Get teams from lookup, fallback to parsing from competitor data
        home_team = teams_lookup.get(home_team_id)
        if not home_team:
            home_team = self._parse_team_from_competitor(home_competitor)

        away_team = teams_lookup.get(away_team_id)
        if not away_team:
            away_team = self._parse_team_from_competitor(away_competitor)

        if not home_team or not away_team:
            return None

        status = competition.get("status", {}).get("type", {})
        state = competition.get("state", "")
        detail = competition.get("detail") or status.get("shortDetail") or ""

        return NFLGame(
            event_id=str(event.get("id")),
            date=_parse_datetime(event.get("date")),
            home_team=home_team,
            away_team=away_team,
            status_state=state,
            status_detail=detail,
            is_completed=bool(status.get("completed")),
            is_live=(state == "in"),
            home_score=_safe_int(home_competitor.get("score", {}).get("displayValue")),
            away_score=_safe_int(away_competitor.get("score", {}).get("displayValue")),
            venue=self._extract_venue(competition),
        )

    def _parse_team_from_competitor(self, competitor: dict) -> Optional[NFLTeam]:
        """Parse team data from competitor data in schedule (fallback method)."""
        team_info = competitor.get("team", {})
        if not team_info:
            return None

        logos = team_info.get("logos") or []
        logo_url = _pick_logo_url(logos)

        color_primary = team_info.get("color") or ""
        color_secondary = team_info.get("alternateColor") or ""

        if color_primary:
            color_primary = _hex_to_rgb(color_primary)
        if color_secondary:
            color_secondary = _hex_to_rgb(color_secondary)

        return NFLTeam(
            id=str(team_info.get("id")),
            display_name=team_info.get("displayName") or team_info.get("name") or "",
            abbreviation=team_info.get("abbreviation") or "",
            location=team_info.get("location") or "",
            name=team_info.get("name") or "",
            color_primary=color_primary,
            color_secondary=color_secondary,
            record_summary="",  # Not available in competitor data
            record_comment=None,
            logo_url=logo_url,
        )

    def _extract_venue(self, competition: dict) -> Optional[str]:
        venue = competition.get("venue") or {}
        if venue.get("fullName"):
            return venue.get("fullName")
        address = venue.get("address") or {}
        if address.get("city") and address.get("state"):
            return f"{address['city']}, {address['state']}"
        if address.get("city"):
            return address.get("city")
        return None
