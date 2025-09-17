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
    """Minimal game information used by the board."""

    event_id: str
    date: Optional[datetime]
    opponent_name: str
    opponent_abbr: str
    opponent_location: str
    is_home: bool
    status_state: str
    status_detail: str
    is_completed: bool
    is_live: bool
    our_score: Optional[int]
    opponent_score: Optional[int]
    venue: Optional[str] = None

    def result_token(self) -> Optional[str]:
        """Return ``W``/``L``/``T`` once the contest is final."""
        if not self.is_completed or self.our_score is None or self.opponent_score is None:
            return None
        if self.our_score > self.opponent_score:
            return "W"
        if self.our_score < self.opponent_score:
            return "L"
        return "T"


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

        team = self._parse_team(team_json)
        games = self._parse_schedule(schedule_json, team_id)

        if team.logo_url:
            team.logo_path = self._ensure_logo(team.abbreviation, team.logo_url)

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

    def _parse_schedule(self, payload: dict, team_id: str) -> list[NFLGame]:
        events = payload.get("events", [])
        games: list[NFLGame] = []
        team_id = str(team_id)

        for event in events:
            game = self._parse_game(event, team_id)
            if game:
                games.append(game)
        return games

    def _parse_game(self, event: dict, team_id: str) -> Optional[NFLGame]:
        competitions = event.get("competitions", [])
        competition = competitions[0] if competitions else {}

        competitors = competition.get("competitors", [])
        our_side = None
        opponent_side = None

        for comp in competitors:
            team = comp.get("team", {})
            comp_id = str(team.get("id") or comp.get("id"))
            if comp_id == team_id:
                our_side = comp
            else:
                opponent_side = comp

        if our_side is None or opponent_side is None:
            return None

        status = competition.get("status", {}).get("type", {})
        state = competition.get("state", "")
        detail = competition.get("detail") or status.get("shortDetail") or ""

        opponent_team = opponent_side.get("team", {})

        return NFLGame(
            event_id=str(event.get("id")),
            date=_parse_datetime(event.get("date")),
            opponent_name=opponent_team.get("displayName") or opponent_team.get("name") or "",
            opponent_abbr=opponent_team.get("abbreviation") or "",
            opponent_location=opponent_team.get("location") or "",
            is_home=(our_side.get("homeAway") == "home"),
            status_state=state,
            status_detail=detail,
            is_completed=bool(status.get("completed")),
            is_live=(state == "in"),
            our_score=_safe_int(our_side.get("score", {}).get("displayValue" or None)),
            opponent_score=_safe_int(opponent_side.get("score", {}).get("displayValue" or None)),
            venue=self._extract_venue(competition),
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
