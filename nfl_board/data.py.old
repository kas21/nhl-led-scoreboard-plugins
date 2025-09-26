"""Utility classes and helpers for the NFL board."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
    quarter: Optional[str] = None
    time_remaining: Optional[str] = None
    possession_team_id: Optional[str] = None

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

    def has_possession(self, team_id: str) -> bool:
        """Check if the specified team has possession."""
        return self.possession_team_id == team_id

    def get_possession_team(self) -> Optional[NFLTeam]:
        """Get the team that currently has possession."""
        if self.possession_team_id == self.home_team.id:
            return self.home_team
        elif self.possession_team_id == self.away_team.id:
            return self.away_team
        return None


class NFLApiClient:
    """Pure data layer for ESPN NFL API - no business logic, just data fetching and parsing."""

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"

    def __init__(self, logo_dir: Path, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.logo_dir = logo_dir
        self.logo_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------------
    # Public API - Simple data access methods

    def get_teams(self) -> list[NFLTeam]:
        """Get all NFL teams."""
        all_teams_json = self._get_json("teams")
        teams_lookup = self._build_teams_lookup(all_teams_json)
        return list(teams_lookup.values())

    def get_team(self, team_id: str) -> NFLTeam:
        """Get detailed information for a specific team."""
        team_json = self._get_json(f"teams/{team_id}")
        team = self._parse_team(team_json)

        # Ensure team logo
        if team.logo_url:
            team.logo_path = self._ensure_logo(team.abbreviation, team.logo_url)

        return team

    def get_team_schedule(self, team_id: str) -> list[NFLGame]:
        """Get full schedule for a specific team."""
        schedule_json = self._get_json(f"teams/{team_id}/schedule")
        all_teams_json = self._get_json("teams")
        teams_lookup = self._build_teams_lookup(all_teams_json)

        all_games = self._parse_all_games(schedule_json, teams_lookup)
        team_games = self._filter_team_games(all_games, team_id)

        # Ensure logos for all games
        for game in team_games:
            if game.home_team.logo_url and not game.home_team.logo_path:
                game.home_team.logo_path = self._ensure_logo(game.home_team.abbreviation, game.home_team.logo_url)
            if game.away_team.logo_url and not game.away_team.logo_path:
                game.away_team.logo_path = self._ensure_logo(game.away_team.abbreviation, game.away_team.logo_url)

        return team_games

    def get_scoreboard(self, date: str = None) -> list[NFLGame]:
        """Get games from scoreboard (current week if no date specified)."""
        url = "scoreboard"
        if date:
            url = f"scoreboard?dates={date}"

        scoreboard_json = self._get_json(url)
        all_teams_json = self._get_json("teams")
        teams_lookup = self._build_teams_lookup(all_teams_json)

        games = self._parse_all_games(scoreboard_json, teams_lookup)

        # Ensure logos for all games
        for game in games:
            if game.home_team.logo_url and not game.home_team.logo_path:
                game.home_team.logo_path = self._ensure_logo(game.home_team.abbreviation, game.home_team.logo_url)
            if game.away_team.logo_url and not game.away_team.logo_path:
                game.away_team.logo_path = self._ensure_logo(game.away_team.abbreviation, game.away_team.logo_url)

        return games

    def get_live_scores(self, game_ids: list[str]) -> dict[str, NFLGame]:
        """Get updated scores for live games."""
        scoreboard_json = self._get_json("scoreboard")
        all_teams_json = self._get_json("teams")
        teams_lookup = self._build_teams_lookup(all_teams_json)

        current_games = self._parse_all_games(scoreboard_json, teams_lookup)
        live_scores = {}

        for game in current_games:
            if game.event_id in game_ids and game.is_live:
                # Update with latest live data
                updated_game = self.update_live_game_scores(game)
                live_scores[game.event_id] = updated_game

        return live_scores


    def update_live_game_scores(self, live_game: NFLGame) -> NFLGame:
        """Update live game with current scores from scoreboard API."""
        try:
            scoreboard_json = self._get_json("scoreboard")

            # Find matching game by event_id
            for game in scoreboard_json.get("events", []):
                if str(game.get("id")) == live_game.event_id:
                    # Update scores and status from live data
                    competitions = game.get("competitions", [])
                    if competitions:
                        competition = competitions[0]
                        competitors = competition.get("competitors", [])

                        for comp in competitors:
                            if comp.get("homeAway") == "home":
                                live_game.home_score = _safe_int(comp.get("score", None))
                            else:
                                live_game.away_score = _safe_int(comp.get("score", None))

                        # Update status information
                        status = competition.get("status", {}).get("type", {})
                        live_game.status_state = status.get("state", live_game.status_state)
                        live_game.status_detail = competition.get("detail") or status.get("shortDetail") or live_game.status_detail
                        live_game.is_completed = bool(status.get("completed"))
                        live_game.is_live = (live_game.status_state == "in")

                        # Update quarter, time, and possession for live games
                        if live_game.is_live:
                            # Get quarter and time from status
                            quarter = status.get("period")
                            if quarter:
                                live_game.quarter = str(quarter)

                            # Get clock time
                            clock = status.get("clock")
                            if clock:
                                live_game.time_remaining = str(clock)

                            # Get possession information if available
                            situation = competition.get("situation")
                            if situation:
                                possession_info = situation.get("possession")
                                if possession_info:
                                    live_game.possession_team_id = str(possession_info)
                    break

        except Exception as exc:
            debug.error(f"NFL board: failed to update live game scores - {exc}")

        return live_game

    # ------------------------------------------------------------------
    # Internal helpers

    def _get_json(self, path: str) -> dict:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        debug.log(f"NFL board: fetching {url}")
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

    def _parse_all_games(self, payload: dict, teams_lookup: dict[str, NFLTeam]) -> list[NFLGame]:
        """Parse all games from schedule or scoreboard data, regardless of team."""
        events = payload.get("events", [])
        games: list[NFLGame] = []

        for event in events:
            game = self._parse_game_data(event, teams_lookup)
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

    def _parse_game_data(self, event: dict, teams_lookup: dict[str, NFLTeam]) -> Optional[NFLGame]:
        """Parse game data for any game, regardless of team involvement."""
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
        state = status.get("state", "")
        detail = competition.get("detail") or status.get("shortDetail") or ""

        # Extract quarter and time information
        quarter = None
        time_remaining = None
        possession_team_id = None

        if state == "in":  # Only extract live game details for in-progress games
            # Get quarter and time from status
            quarter = status.get("period")
            if quarter:
                quarter = str(quarter)

            # Get clock time
            clock = status.get("clock")
            if clock:
                time_remaining = str(clock)

            # Get possession information if available
            situation = competition.get("situation", None)
            if situation:
                possession_info = situation.get("possession", None)
                if possession_info:
                    possession_team_id = str(possession_info or "")

        return NFLGame(
            event_id=str(event.get("id")),
            date=_parse_datetime(event.get("date")),
            home_team=home_team,
            away_team=away_team,
            status_state=state,
            status_detail=detail,
            is_completed=bool(status.get("completed")),
            is_live=(state == "in"),
            home_score=_safe_int(home_competitor.get("score", {})),
            away_score=_safe_int(away_competitor.get("score", {})),
            venue=self._extract_venue(competition),
            quarter=quarter,
            time_remaining=time_remaining,
            possession_team_id=possession_team_id,
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

    # ------------------------------------------------------------------
    # Core data access helpers (keep these - they're just basic filtering)

    def _filter_team_games(self, games: list[NFLGame], team_id: str) -> list[NFLGame]:
        """Basic filter: games where specified team participates."""
        team_id = str(team_id)
        return [
            game for game in games
            if game.home_team.id == team_id or game.away_team.id == team_id
        ]
