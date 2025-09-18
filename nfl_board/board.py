"""NFL team information board."""
from __future__ import annotations

import datetime
import inspect
from pathlib import Path
from typing import Optional
import threading

import debug
from PIL import Image
import json

from boards.base_board import BoardBase

from . import __board_name__, __description__, __version__
from .data import NFLApiClient, NFLGame, NFLTeam
from renderer.matrix import Matrix


class NFLBoard(BoardBase):
    """Display upcoming and recent game information for an NFL franchise."""

    def __init__(self, data, matrix: Matrix, sleepEvent):
        super().__init__(data, matrix, sleepEvent)

        self.board_name = __board_name__
        self.board_version = __version__
        self.board_description = __description__

        self.display_seconds = int(self.board_config.get("display_seconds", 8))
        self.refresh_seconds = int(self.board_config.get("refresh_seconds", 300))
        self.team_id = str(self.board_config.get("team_id") or "").strip()

        if not self.team_id:
            debug.error("NFL board: team_id is required in config.json")

        self.board_dir = self._get_board_directory()
        self.api_client = NFLApiClient(self.board_dir / "logos")

        config_path = self.board_dir / "logo_offsets.json"
        if config_path.exists():
            with config_path.open() as fh:
                raw = json.load(fh)
            default = raw.get("_default", {})
            self.logo_offsets = {
                key.upper(): {**default, **value}
                for key, value in raw.items()
                if key != "_default"
            }
            self.logo_offsets["_default"] = default
        else:
            self.logo_offsets = {"_default": {"zoom": 1.0, "offset": (0, 0)}}

        self.team: Optional[NFLTeam] = None
        self.next_game: Optional[NFLGame] = None
        self.last_game: Optional[NFLGame] = None
        self.live_game: Optional[NFLGame] = None
        self._team_logo_cache: dict[tuple[Path, int], Image.Image] = {}

        self.last_refresh = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        self.error_message: Optional[str] = None

        self._lock = threading.RLock()
        self._snapshot = None
        self._scheduled_job_id = "nfl_board_refresh"

        scheduler = getattr(self.data, "scheduler", None)
        if scheduler:
            if not scheduler.get_job(self._scheduled_job_id):
                scheduler.add_job(
                    self._scheduled_refresh,
                    "interval",
                    seconds=self.refresh_seconds,
                    id=self._scheduled_job_id,
                    max_instances=1,
                    replace_existing=True,
                )
                debug.info("NFL Data Refresh Scheduled")
        else:
            debug.info("Scheduling Failed: forcing refresh")
            self._scheduled_refresh()

        self._snapshot = getattr(self.data, "nfl_board_snapshot", None)
        if self._snapshot is None:
            self._scheduled_refresh()
        else:
            self.team = self._snapshot.get("team")
            self.live_game = self._snapshot.get("live_game")
            self.last_game = self._snapshot.get("last_game")
            self.next_game = self._snapshot.get("next_game")


    # ------------------------------------------------------------------
    # Board lifecycle

    def render(self):
        self.matrix.clear()

        with self._lock:
            snapshot = self._snapshot

        if snapshot is None:
            self._scheduled_refresh()
            with self._lock:
                snapshot = self._snapshot

        layout = self.get_board_layout("nfl_board")
        if layout is None:
            debug.error("NFL board: layout not found")
            return

        if snapshot is None:
            self._draw_text(layout, "primary_label", "NFL")
            self._draw_text(layout, "primary_line1", "Loading…")
            self.matrix.render()
            self.sleepEvent.wait(self.display_seconds)
            return

        # Hydrate locals from snapshot data
        team = snapshot.get("team")
        error = snapshot.get("error")
        live_game = snapshot.get("live_game")
        last_game = snapshot.get("last_game")
        next_game = snapshot.get("next_game")

        if error and not team:
            self._draw_text(layout, "primary_label", "NFL")
            self._draw_text(layout, "primary_line1", error)
            self.matrix.render()
            self.sleepEvent.wait(self.display_seconds)
            return

        if team:
            self._draw_logo(layout)
            self.matrix.draw_text_layout(layout.team_name, team.display_name, fillColor=team.color_primary, backgroundColor=team.color_secondary)
            #self._draw_text(layout, "team_name", team.display_name)
            self.matrix.draw_text_layout(layout.record_header, "RECORD:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
            #self.matrix.draw_text_layout(layout.last_game_header, "LAST GAME:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
            self._draw_text(layout, "record", team.record_summary)
            self._draw_text(layout, "record_comment", team.record_comment)
            self.matrix.draw_text_layout(layout.next_game_header, "NEXT GAME:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
            self.matrix.draw_text_layout(layout.next_game, self._format_opponent(self.next_game))
            self.matrix.draw_text_layout(layout.last_game_header, "LAST GAME:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
            #self.matrix.draw_text_layout(layout.last_game, self._format_opponent(self.last_game))
            self.matrix.draw_text_layout(layout.last_game_result, self._format_game_result(self.last_game))


        self.matrix.render()
        self.sleepEvent.wait(self.display_seconds)

    # ------------------------------------------------------------------
    # Internal helpers

    def _get_board_directory(self) -> Path:
        board_file = inspect.getfile(self.__class__)
        return Path(board_file).resolve().parent

    # def _needs_refresh(self, now: datetime.datetime) -> bool:
    #     if not self.team:
    #         return True
    #     delta = (now - self.last_refresh).total_seconds()
    #     return delta >= self.refresh_seconds

    def _scheduled_refresh(self):
        try:
            snapshot = self._fetch_snapshot()
            self.data.nfl_board_snapshot = snapshot
        except Exception as exc:
            debug.error(f"NFL board: background refresh failed - {exc}")
            snapshot = {"error": "NFL data unavailable", "timestamp": datetime.datetime.now(datetime.timezone.utc)}
        with self._lock:
            self._snapshot = snapshot
            self.team = snapshot.get("team")
            self.live_game = snapshot.get("live_game")
            self.last_game = snapshot.get("last_game")
            self.next_game = snapshot.get("next_game")
            self.error_message = snapshot.get("error")
            self.last_refresh = snapshot.get("timestamp", datetime.datetime.now(datetime.timezone.utc))

    
    def _fetch_snapshot(self):
        team, games = self.api_client.fetch_team_payload(self.team_id)

        live_game = next((g for g in games if g.is_live), None)
        min_dt = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        max_dt = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)
        completed = sorted((g for g in games if g.is_completed), key=lambda g: g.date or min_dt)
        upcoming = sorted((g for g in games if not g.is_completed and not g.is_live), key=lambda g: g.date or max_dt)

        snapshot = {
            "team": team,
            "live_game": live_game,
            "last_game": completed[-1] if completed else None,
            "next_game": upcoming[0] if upcoming else None,
            "error": None,
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
        }
        return snapshot

    def _draw_text(self, layout, element: str, text: Optional[str]) -> None:
        if not text:
            return
        if not hasattr(layout, element):
            return
        self.matrix.draw_text_layout(getattr(layout, element), str(text))

    def _draw_logo(self, layout) -> None:
        if not hasattr(layout, "team_logo") or not self.team or not self.team.logo_path:
            return

        offsets = self.logo_offsets.get(self.team.abbreviation, self.logo_offsets["_default"])
        zoom = float(offsets.get("zoom", 1.0))
        offset_x, offset_y = offsets.get("offset", (0, 0))

        base_key = (self.team.logo_path, 0)
        base_logo = self._team_logo_cache.get(base_key)
        if base_logo is None:
            with Image.open(self.team.logo_path) as img:
                base_logo = img.convert("RGBA").copy()
            self._team_logo_cache[base_key] = base_logo

        max_dimension = 64 if self.matrix.height >= 48 else min(32, self.matrix.height)
        scaled_key = (self.team.logo_path, max_dimension)
        logo = self._team_logo_cache.get(scaled_key)
        if logo is None:
            logo = base_logo.copy()
            if max(logo.size) > max_dimension:
                logo.thumbnail((max_dimension, max_dimension), self._thumbnail_filter())
            self._team_logo_cache[scaled_key] = logo

        if zoom != 1.0:
            zoom_key = (self.team.logo_path, max_dimension, zoom)
            zoomed = self._team_logo_cache.get(zoom_key)
            if zoomed is None:
                w, h = logo.size
                zoomed = logo.resize(
                    (max(1, int(round(w * zoom))), max(1, int(round(h * zoom)))),
                    self._thumbnail_filter(),
                )
                self._team_logo_cache[zoom_key] = zoomed
            logo = zoomed

        element = layout.team_logo.__copy__()
        x, y = element.position
        element.position = (x + offset_x, y + offset_y)

        self.matrix.draw_image_layout(element, logo)

    @staticmethod
    def _thumbnail_filter():
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
        if resampling is None:
            resampling = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
        return resampling

    def _format_opponent(self, game: NFLGame) -> str:
        prefix = "VS" if game.is_home else "AT"
        opponent = game.opponent_location or game.opponent_abbr or game.opponent_name
        return f"{prefix} {opponent}".strip()

    def _format_game_time(self, game: NFLGame) -> Optional[str]:
        if not game.date:
            return game.status_detail or None
        local_dt = game.date.astimezone()
        weekday = local_dt.strftime("%a")
        hour = local_dt.hour % 12 or 12
        minute = local_dt.minute
        ampm = "AM" if local_dt.hour < 12 else "PM"
        return f"{weekday} {local_dt.month}/{local_dt.day} {hour}:{minute:02d} {ampm}"

    def _format_game_result(self, game: NFLGame) -> str:
        result = game.result_token() or ""
        score = ""
        if game.our_score is not None and game.opponent_score is not None:
            score = f"{game.our_score}-{game.opponent_score}"
        opponent = self._format_opponent(game)
        return " ".join(part for part in [result, score, opponent] if part)

    def _format_last_detail(self, game: NFLGame) -> Optional[str]:
        if game.is_completed and game.status_detail:
            return game.status_detail
        if game.venue:
            return game.venue
        return None

    def _format_live_line(self, game: NFLGame) -> str:
        opponent = game.opponent_abbr or game.opponent_name
        our_score = game.our_score if game.our_score is not None else 0
        opp_score = game.opponent_score if game.opponent_score is not None else 0
        team_abbr = self.team.abbreviation if self.team else ""
        return f"{team_abbr} {our_score}-{opp_score} {opponent}".strip()
