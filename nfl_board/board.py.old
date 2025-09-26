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
from utils import get_file

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

        # Read basic settings
        self.display_seconds = int(self.board_config.get("display_seconds", 8))
        self.refresh_seconds = int(self.board_config.get("refresh_seconds", 300))
        self.show_todays_games = bool(self.board_config.get("show_todays_games", False))
        self.show_previous_games_until = self.board_config.get("show_previous_games_until", "06:00")
        self.team_ids = self.board_config.get("team_ids", [])

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


        # Validate that we have at least one team_id
        if not self.team_ids:
            debug.error("NFL board: team_id (single or list) is required in config.json")
            return

        debug.info(f"NFL board: configured for {len(self.team_ids)} favorite teams: {self.team_ids}")

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

        layout = self.get_board_layout("nfl_team_summary")
        if layout is None:
            debug.error("NFL board: layout not found")
            return

        if snapshot is None:
            self._draw_text(layout, "primary_label", "NFL")
            self._draw_text(layout, "primary_line1", "Loading…")
            self.matrix.render()
            self.sleepEvent.wait(self.display_seconds)
            return

        # Extract data from snapshot
        favorite_teams = snapshot.get("favorite_teams", {})
        favorite_team_games = snapshot.get("favorite_team_games", [])
        favorite_game_team_ids = snapshot.get("favorite_game_team_ids", set())
        other_games = snapshot.get("other_games", [])
        todays_games = snapshot.get("todays_games", [])  # Filtered games for display
        team_schedule_games = snapshot.get("team_schedule_games", {})  # Unfiltered schedule data for next/last games
        error = snapshot.get("error")

        # Handle error case
        if error and not favorite_teams:
            self._draw_text(layout, "primary_label", "NFL")
            self._draw_text(layout, "primary_line1", error)
            self.matrix.render()
            self.sleepEvent.wait(self.display_seconds)
            return

        # New flow: Handle favorite teams first
        self._render_favorite_teams(favorite_teams, favorite_team_games, favorite_game_team_ids, todays_games, team_schedule_games)

        # Then show other games if setting is enabled
        if self.show_todays_games and other_games:
            self._render_other_games(other_games)

    def _render_favorite_teams(self, favorite_teams: dict, favorite_team_games: list, favorite_game_team_ids: set, all_available_games: list = None, team_schedule_games: dict = None):
        """
        Render favorite teams: show game board if team has game today, otherwise show team summary.
        """
        if all_available_games is None:
            all_available_games = favorite_team_games  # Use favorite team games as fallback
        if team_schedule_games is None:
            team_schedule_games = {}
        for team_id in self.team_ids:
            # Check if this favorite team has a game today
            if team_id in favorite_game_team_ids:
                # Team has a game today - find and show the game
                team_game = None
                for game in favorite_team_games:
                    if game.home_team.id == team_id or game.away_team.id == team_id:
                        team_game = game
                        break

                if team_game:
                    debug.log(f"Showing game for favorite team {team_id}")
                    self._render_game(team_game)
            else:
                # Team has no game today - show team summary if we have team data
                if team_id in favorite_teams:
                    team = favorite_teams[team_id]
                    debug.log(f"Showing team summary for favorite team {team_id} (no game today)")

                    # Use schedule data for this team if available, otherwise fall back to all available games
                    team_schedule = team_schedule_games.get(team_id, all_available_games)
                    debug.log(f"Using {len(team_schedule)} schedule games for team {team_id} summary")

                    self._render_team_summary(team, team_schedule)
                else:
                    debug.warning(f"No data available for favorite team {team_id}")

    def _render_other_games(self, other_games: list):
        """
        Render games that don't involve favorite teams.
        """
        debug.log(f"Showing {len(other_games)} other games")
        # Sort games by date to show them in chronological order
        sorted_other_games = sorted(other_games, key=lambda x: x.date or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))

        for game in sorted_other_games:
            self._render_game(game)


    # Render Team Summary
    def _render_team_summary(self, team: NFLTeam, available_games: list[NFLGame] = None):
        layout = self.get_board_layout("nfl_team_summary")

        self.matrix.clear()

        # Use available games or fall back to empty list
        if available_games is None:
            available_games = []

        # Find next and last games for this specific team
        next_game = self._get_next_game_for_team(team.id, available_games)
        last_game = self._get_last_game_for_team(team.id, available_games)

        self._draw_logo(layout, "team_logo", team.logo_path, team.abbreviation)
        self.matrix.draw_text_layout(layout.team_name, team.display_name, fillColor=team.color_primary, backgroundColor=team.color_secondary)
        self.matrix.draw_text_layout(layout.record_header, "RECORD:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
        self._draw_text(layout, "record", team.record_summary)
        self._draw_text(layout, "record_comment", team.record_comment)

        # Next game section
        self.matrix.draw_text_layout(layout.next_game_header, "NEXT GAME:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
        next_game_time = self._format_game_time(next_game) or ""
        next_game_opponent = self._format_opponent(next_game, team.id)
        next_game_text = f"{next_game_time} {next_game_opponent}".strip()
        if not next_game_text:
            next_game_text = "No games scheduled"
        self.matrix.draw_text_layout(layout.next_game, next_game_text)

        # Last game section
        self.matrix.draw_text_layout(layout.last_game_header, "LAST GAME:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
        last_game_result = self._format_game_result(last_game, team.id)
        self.matrix.draw_text_layout(layout.last_game_result, last_game_result)

        self.matrix.render()
        self.sleepEvent.wait(self.display_seconds)
    
    def _render_game(self, game: NFLGame):
        self.matrix.clear()

        layout = self.get_board_layout("nfl_live_game")

        # Draw home logo
        self._draw_logo(
            layout, 
            "home_team_logo", 
            game.home_team.logo_path, 
            game.home_team.abbreviation
        )

        # Draw away logo
        self._draw_logo(
            layout, 
            "away_team_logo", 
            game.away_team.logo_path, 
            game.away_team.abbreviation
        )

        gradient = self._load_gradient()
        self.matrix.draw_image([self.matrix.width/2,0], gradient, align="center")

        if game.is_live or game.is_completed:
            #self.matrix.draw_text_layout(layout.scheduled_date, "LIVE")
            if game.is_live:
                t, q = game.status_detail.split("-")
            else:
                t, q = "", game.status_detail
            #self.matrix.draw_text_layout(layout.quarter, str(live_game.status_detail))
            self.matrix.draw_text_layout(layout.scheduled_date, t.strip().upper())
            self.matrix.draw_text_layout(layout.scheduled_time, q.strip().upper())
            score = f"{game.away_score}-{game.home_score}"
            self.matrix.draw_text_layout(layout.score, score)
        else:
            self.matrix.draw_text_layout(layout.scheduled_date, "TODAY")
            self.matrix.draw_text_layout(layout.scheduled_time, self._format_game_time(game, format_type="time_only"))
            self.matrix.draw_text_layout(layout.VS, "VS")

        self.matrix.render()
        self.sleepEvent.wait(self.display_seconds)


    # ------------------------------------------------------------------
    # Internal helpers

    def _get_board_directory(self) -> Path:
        board_file = inspect.getfile(self.__class__)
        return Path(board_file).resolve().parent

    def _load_gradient(self) -> Image.Image:
        """Load appropriate gradient image for current matrix size."""
        if self.matrix.height >= 48:
            return Image.open(get_file('assets/images/128x64_scoreboard_center_gradient.png'))
        else:
            return Image.open(get_file('assets/images/64x32_scoreboard_center_gradient.png'))


    def _scheduled_refresh(self):
        try:
            snapshot = self._fetch_snapshot()
            self.data.nfl_board_snapshot = snapshot
        except Exception as exc:
            import traceback
            debug.error(f"NFL board: background refresh failed - {exc}")
            debug.error(traceback.print_exc())
            snapshot = {"error": "NFL data unavailable", "timestamp": datetime.datetime.now(datetime.timezone.utc)}
        with self._lock:
            self._snapshot = snapshot
            self.error_message = snapshot.get("error")
            self.last_refresh = snapshot.get("timestamp", datetime.datetime.now(datetime.timezone.utc))

    
    def _fetch_snapshot(self):
        """
        Fetch NFL data.
        """
        try:
            snapshot = self._fetch_data()
            return snapshot

        except Exception as exc:
            debug.error(f"NFL board: failed to fetch snapshot - {exc}")
            return {
                "favorite_teams": {},
                "favorite_team_games": [],
                "favorite_game_team_ids": set(),
                "other_games": [],
                "todays_games": [],
                "team_schedule_games": {},
                "error": f"Failed to fetch NFL data: {exc}",
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
            }

    def _fetch_data(self) -> dict:
        debug.info(f"Fetching NFL data from API")

        # Step 1: Get current games from scoreboard
        current_games = self.api_client.get_scoreboard()
        debug.log(f"Fetched {len(current_games)} games from current scoreboard")

        # Step 2: Get favorite team data
        favorite_teams = {}
        team_schedule_games = {}

        for team_id in self.team_ids:
            try:
                if self.show_todays_games:
                    # Get detailed team info when showing all games
                    team = self.api_client.get_team(team_id)
                    schedule = self.api_client.get_team_schedule(team_id)
                else:
                    # Get basic team info when memory optimized
                    all_teams = self.api_client.get_teams()
                    team = next((t for t in all_teams if t.id == team_id), None)
                    schedule = self.api_client.get_team_schedule(team_id)  # Still need for next/last games

                if team:
                    favorite_teams[team_id] = team
                    team_schedule_games[team_id] = schedule
                    debug.log(f"Loaded {len(schedule)} schedule games for team {team_id}")

            except Exception as exc:
                debug.error(f"Failed to fetch data for team {team_id}: {exc}")
                team_schedule_games[team_id] = []

        # Step 3: Handle previous games based on time settings
        display_games = current_games.copy()

        if self.show_previous_games_until:
            if self._should_show_previous_games(self.show_previous_games_until):
                # Fetch additional previous games if needed
                previous_games = self._get_previous_games_if_needed()
                display_games.extend(previous_games)
                debug.log(f"Added {len(previous_games)} previous games")
            else:
                # Filter out old completed games
                display_games = self._filter_games_by_time_cutoff(display_games, self.show_previous_games_until)
                debug.log(f"Filtered games based on time cutoff")

        # Step 4: Apply business logic filtering (after time filtering)

        # Filter time-filtered games for favorite teams
        favorite_team_games = self._filter_games_by_teams(display_games, self.team_ids)

        # Get other games (when showing all)
        if self.show_todays_games:
            other_games = [
                game for game in display_games
                if game.home_team.id not in self.team_ids and game.away_team.id not in self.team_ids
            ]
        else:
            other_games = []

        # Step 5: Update live games
        live_games = self._filter_live_games(display_games)
        if live_games:
            live_game_ids = [game.event_id for game in live_games]
            updated_scores = self.api_client.get_live_scores(live_game_ids)

            # Update games with live scores
            for i, game in enumerate(display_games):
                if game.event_id in updated_scores:
                    display_games[i] = updated_scores[game.event_id]

        # Step 6: Build snapshot
        favorite_game_team_ids = set()
        for game in favorite_team_games:
            if game.home_team.id in self.team_ids:
                favorite_game_team_ids.add(game.home_team.id)
            if game.away_team.id in self.team_ids:
                favorite_game_team_ids.add(game.away_team.id)

        return {
            "favorite_teams": favorite_teams,
            "favorite_team_games": favorite_team_games,
            "favorite_game_team_ids": favorite_game_team_ids,
            "other_games": other_games,
            "todays_games": display_games,
            "team_schedule_games": team_schedule_games,
            "error": None,
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
        }

    def _get_previous_games_if_needed(self) -> list[NFLGame]:
        """Get previous games when we're before the cutoff time."""
        try:
            # Use the date range method to get games from previous days
            extended_games = self._get_games_for_date_range(start_days_ago=3, end_days_ahead=0)

            # Filter to only completed games from previous days
            today = datetime.datetime.now().date()
            previous_games = []

            for game in extended_games:
                if game.is_completed and game.date:
                    game_date = game.date.astimezone().date()
                    if game_date < today:
                        previous_games.append(game)

            return previous_games

        except Exception as exc:
            debug.error(f"Failed to get previous games: {exc}")
            return []


    def _draw_text(self, layout, element: str, text: Optional[str]) -> None:
        if not text:
            return
        if not hasattr(layout, element):
            return
        self.matrix.draw_text_layout(getattr(layout, element), str(text))

    def _draw_logo(self, layout, element_name: str, logo_path: Path, team_abbreviation: str) -> None:
        """
        Draw a team logo using element-specific offsets.

        Args:
            layout: Layout object containing the logo element
            element_name: Name of the logo element (also used as offset key)
            logo_path: Path to the logo image file
            team_abbreviation: Team abbreviation for offset lookup
        """
        if not hasattr(layout, element_name) or not logo_path or not logo_path.exists():
            return

        # Use element_name as the offset key
        offsets = self._get_logo_offsets(team_abbreviation, element_name)

        zoom = float(offsets.get("zoom", 1.0))
        offset_x, offset_y = offsets.get("offset", (0, 0))

        # Load and cache the base logo
        base_key = (logo_path, 0)
        base_logo = self._team_logo_cache.get(base_key)
        if base_logo is None:
            with Image.open(logo_path) as img:
                base_logo = img.convert("RGBA").copy()
            self._team_logo_cache[base_key] = base_logo

        # Scale logo to appropriate size
        max_dimension = 64 if self.matrix.height >= 48 else min(32, self.matrix.height)
        scaled_key = (logo_path, max_dimension)
        logo = self._team_logo_cache.get(scaled_key)
        if logo is None:
            logo = base_logo.copy()
            if max(logo.size) > max_dimension:
                logo.thumbnail((max_dimension, max_dimension), self._thumbnail_filter())
            self._team_logo_cache[scaled_key] = logo

        # Apply zoom if needed
        if zoom != 1.0:
            zoom_key = (logo_path, max_dimension, zoom, element_name)
            zoomed = self._team_logo_cache.get(zoom_key)
            if zoomed is None:
                w, h = logo.size
                zoomed = logo.resize(
                    (max(1, int(round(w * zoom))), max(1, int(round(h * zoom)))),
                    self._thumbnail_filter(),
                )
                self._team_logo_cache[zoom_key] = zoomed
            logo = zoomed

        # Apply offset to layout element
        element = getattr(layout, element_name).__copy__()
        x, y = element.position
        element.position = (x + offset_x, y + offset_y)

        self.matrix.draw_image_layout(element, logo)

    def _get_logo_offsets(self, team_abbreviation: str, element_name: str) -> dict:
        """Get logo offsets for a team and element, with fallback hierarchy."""
        team_offsets = self.logo_offsets.get(team_abbreviation.upper())

        if isinstance(team_offsets, dict):
            # Check for element-specific offset (e.g., "home_team_logo", "team_logo")
            if element_name in team_offsets:
                return team_offsets[element_name]
            # Fall back to team default
            if "_default" in team_offsets:
                return team_offsets["_default"]

        # Fall back to global default
        return self.logo_offsets.get("_default", {"zoom": 1.0, "offset": (0, 0)})

    @staticmethod
    def _thumbnail_filter():
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
        if resampling is None:
            resampling = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
        return resampling

    def _format_opponent(self, game: Optional[NFLGame], team_id: str) -> str:
        if not game:
            return "No games scheduled"

        opponent = game.get_opponent(team_id)
        if not opponent:
            return "Unknown"

        prefix = "VS" if game.is_home_team(team_id) else "AT"
        opponent_text = opponent.location or opponent.abbreviation or opponent.name
        return f"{prefix} {opponent_text}".strip()

    def _format_game_time(self, game: Optional[NFLGame], format_type: str = "full") -> Optional[str]:
        """Format game time with flexible output options.

        Args:
            game: NFLGame object (can be None)
            format_type: "full", "time_only", "date_only", or "short"

        Returns:
            Formatted time string or None
        """
        if not game:
            return None
        if not game.date:
            return game.status_detail or None
        local_dt = game.date.astimezone()

        if format_type == "time_only":
            hour = local_dt.hour % 12 or 12
            minute = local_dt.minute
            ampm = "AM" if local_dt.hour < 12 else "PM"
            return f"{hour}:{minute:02d} {ampm}"
        elif format_type == "date_only":
            return f"{local_dt.strftime('%a')} {local_dt.month}/{local_dt.day}"
        elif format_type == "short":
            hour = local_dt.hour % 12 or 12
            minute = local_dt.minute
            ampm = "AM" if local_dt.hour < 12 else "PM"
            return f"{local_dt.month}/{local_dt.day} {hour}:{minute:02d} {ampm}"
        else:  # "full" (default)
            weekday = local_dt.strftime("%a")
            hour = local_dt.hour % 12 or 12
            minute = local_dt.minute
            ampm = "AM" if local_dt.hour < 12 else "PM"
            return f"{weekday} {local_dt.month}/{local_dt.day} {hour}:{minute:02d} {ampm}"

    def _format_game_result(self, game: Optional[NFLGame], team_id: str) -> str:
        if not game:
            return "No recent games"

        result = game.result_token(team_id) or ""
        score = ""
        our_score = game.get_team_score(team_id)
        opponent_score = game.get_opponent_score(team_id)
        if our_score is not None and opponent_score is not None:
            score = f"{our_score}-{opponent_score}"
        opponent = self._format_opponent(game, team_id)
        return " ".join(part for part in [result, score, opponent] if part)

    def _get_next_game_for_team(self, team_id: str, games: list[NFLGame]) -> Optional[NFLGame]:
        """Find the next upcoming game for a specific team."""
        upcoming_games = []
        for game in games:
            if (game.home_team.id == team_id or game.away_team.id == team_id) and not game.is_completed and not game.is_live:
                upcoming_games.append(game)

        if not upcoming_games:
            return None

        # Sort by date and return the earliest one
        upcoming_games.sort(key=lambda g: g.date or datetime.datetime.max.replace(tzinfo=datetime.timezone.utc))
        return upcoming_games[0]

    def _get_last_game_for_team(self, team_id: str, games: list[NFLGame]) -> Optional[NFLGame]:
        """Find the most recent completed game for a specific team."""
        completed_games = []
        for game in games:
            if (game.home_team.id == team_id or game.away_team.id == team_id) and game.is_completed:
                completed_games.append(game)

        if not completed_games:
            return None

        # Sort by date and return the most recent one
        completed_games.sort(key=lambda g: g.date or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), reverse=True)
        return completed_games[0]


    # ------------------------------------------------------------------
    # Business Logic Methods (moved from data layer)

    def _filter_games_by_teams(self, games: list[NFLGame], team_ids: list[str]) -> list[NFLGame]:
        """Filter games to only include those involving specified teams."""
        team_ids_set = set(str(tid) for tid in team_ids)
        return [
            game for game in games
            if game.home_team.id in team_ids_set or game.away_team.id in team_ids_set
        ]


    def _filter_completed_games(self, games: list[NFLGame]) -> list[NFLGame]:
        """Filter games to only include completed games."""
        return [game for game in games if game.is_completed]

    def _filter_live_games(self, games: list[NFLGame]) -> list[NFLGame]:
        """Filter games to only include currently live games."""
        return [game for game in games if game.is_live]

    def _filter_upcoming_games(self, games: list[NFLGame]) -> list[NFLGame]:
        """Filter games to only include upcoming games."""
        return [game for game in games if not game.is_completed and not game.is_live]

    def _should_show_previous_games(self, cutoff_time: str) -> bool:
        """Determine if previous games should be shown based on current time vs cutoff."""
        if not cutoff_time:
            return False

        try:
            cutoff_hour, cutoff_minute = map(int, cutoff_time.split(':'))
            now = datetime.datetime.now()
            today_cutoff = now.replace(hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0)
            return now < today_cutoff
        except Exception:
            return False

    def _filter_games_by_time_cutoff(self, games: list[NFLGame], cutoff_time: str) -> list[NFLGame]:
        """Remove old completed games when past the cutoff time."""
        if not cutoff_time or self._should_show_previous_games(cutoff_time):
            return games

        today = datetime.datetime.now().date()
        filtered_games = []

        for game in games:
            if not game.date:
                filtered_games.append(game)
                continue

            game_date = game.date.astimezone().date()

            # Keep games from today and future, remove old completed games
            if game_date >= today:
                filtered_games.append(game)
            elif not game.is_completed:
                # Keep non-completed games from previous days (edge case)
                filtered_games.append(game)

        return filtered_games

    def _get_games_for_date_range(self, start_days_ago: int = 3, end_days_ahead: int = 0) -> list[NFLGame]:
        """Get games from a date range using the data layer."""
        all_games = []
        now = datetime.datetime.now()

        # Fetch games from multiple days
        for days_offset in range(-start_days_ago, end_days_ahead + 1):
            target_date = now + datetime.timedelta(days=days_offset)
            date_str = target_date.strftime("%Y%m%d")

            try:
                if days_offset == 0:
                    # Use current scoreboard for today
                    games = self.api_client.get_scoreboard()
                else:
                    # Use specific date for other days
                    games = self.api_client.get_scoreboard(date_str)
                all_games.extend(games)
            except Exception as exc:
                debug.error(f"Failed to fetch games for {date_str}: {exc}")

        return all_games
