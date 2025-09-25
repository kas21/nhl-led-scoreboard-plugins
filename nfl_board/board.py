"""
NFL Board - Clean Implementation
Displays NFL games and team information using clear, readable logic.
"""

import debug
import json
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional, Dict
from pathlib import Path
from utils import get_file


from PIL import Image
from boards.base_board import BoardBase

from . import __board_name__, __description__, __version__
from .data import NFLApiClient, NFLDataSnapshot, NFLGame, NFLTeam


class NFLBoardConfig:
    """
    Handles NFL board configuration with validation and sensible defaults.
    Makes configuration logic clear and separate from rendering logic.
    """

    def __init__(self, config_data: dict):
        # Team configuration - must have at least one team
        self.team_ids = self._parse_team_ids(config_data.get("team_ids", []))
        if not self.team_ids:
            raise ValueError("NFL Board requires at least one team_id in configuration")

        # Display timing settings
        self.display_seconds = int(config_data.get("display_seconds", 8))
        self.refresh_seconds = int(config_data.get("refresh_seconds", 300))

        # Game display configuration
        self.show_all_games = bool(config_data.get("show_all_games", False))
        self.show_previous_games_until_time = self._parse_cutoff_time(
            config_data.get("show_previous_games_until", "06:00")
        )

        debug.info(f"NFL Board: Configured for teams {self.team_ids}")
        debug.info(f"NFL Board: Show all games = {self.show_all_games}")
        debug.info(f"NFL Board: Previous games cutoff = {self.show_previous_games_until_time}")

    def _parse_team_ids(self, team_ids_config) -> List[str]:
        """Parse team IDs from configuration, handling single string or list."""
        if isinstance(team_ids_config, str):
            team_ids_config = [team_ids_config]

        if not isinstance(team_ids_config, list):
            return []

        # Convert all to strings and filter out empty ones
        parsed_ids = [str(tid).strip() for tid in team_ids_config if str(tid).strip()]
        return parsed_ids

    def _parse_cutoff_time(self, time_string: str) -> time:
        """Parse cutoff time string into time object."""
        try:
            hour, minute = map(int, time_string.split(":"))
            return time(hour, minute)
        except (ValueError, AttributeError):
            debug.warning(f"NFL Board: Invalid cutoff time '{time_string}', using 06:00")
            return time(6, 0)

    def should_show_previous_game(self, game: NFLGame) -> bool:
        """
        Determine if a previous day's game should still be shown.
        Games from yesterday are shown until the configured cutoff time.
        """
        if not game.is_final:
            return True

        now = datetime.now()
        if not game.date:
            return False

        game_date = game.date.date()
        today = now.date()

        # Show games from today or future
        if game_date >= today:
            return True

        # Show games from yesterday if we're before the cutoff time
        if game_date == today - timedelta(days=1):
            return now.time() < self.show_previous_games_until_time

        # Don't show games older than yesterday
        return False


class NFLBoard(BoardBase):
    """
    NFL Board implementation following BoardBase pattern.
    Displays NFL games with clean separation between data fetching and rendering.
    """

    def __init__(self, data, matrix, sleepEvent):
        super().__init__(data, matrix, sleepEvent)

        # Board metadata
        self.board_name = __board_name__
        self.board_version = __version__
        self.board_description = __description__

        # Initialize configuration with validation
        try:
            self.config = NFLBoardConfig(self.board_config)
        except ValueError as error:
            debug.error(f"NFL Board configuration error: {error}")
            raise

        # Initialize API client
        logo_cache_dir = self._get_board_directory() / "logos" if hasattr(self, '_get_board_directory') else None
        self.api_client = NFLApiClient(logo_cache_dir)

        # Display state management - unified approach
        self.current_display_items = []  # Unified list of games and team summaries
        self.last_layout_refresh = datetime.min

        # Logo caching for performance
        self.logo_cache: Dict[str, Image.Image] = {}

        # Load logo positioning offsets if they exist
        self.logo_offsets = self._load_logo_offsets()

        # Gradient used for board
        self.gradient = self._load_gradient()

        # Set up scheduled data refresh using APScheduler
        self._scheduled_job_id = f"nfl_board_data_refresh_{id(self)}"
        self._setup_data_refresh_schedule()

        # Initialize with existing data if available
        existing_snapshot = getattr(self.data, "nfl_board_snapshot", None)
        if existing_snapshot is None:
            # Force initial basic data fetch for immediate display
            self._perform_basic_data_refresh()
            # Schedule full data refresh for background
            scheduler = getattr(self.data, "scheduler", None)
            if scheduler:
                scheduler.add_job(
                    self._perform_full_data_refresh,
                    "date",
                    run_date=datetime.now() + timedelta(seconds=1),
                    id=f"{self._scheduled_job_id}_initial_full",
                    max_instances=1
                )

        debug.info("NFL Board: Initialization complete")

    def validate_config(self) -> bool:
        """Validate NFL board configuration."""
        try:
            if not self.config.team_ids:
                debug.error("NFL Board: No team IDs configured")
                return False

            for team_id in self.config.team_ids:
                if not isinstance(team_id, str) or not team_id.strip():
                    debug.error(f"NFL Board: Invalid team ID: {team_id}")
                    return False

            return True

        except Exception as error:
            debug.error(f"NFL Board: Configuration validation failed: {error}")
            return False

    def render(self):
        """
        Main render method called by the board system.
        Handles data refresh timing and delegates to appropriate render methods.
        """
        debug.info("NFL Board: render() method called")

        try:
            # Update display games if needed
            if self._should_refresh_display_games():
                debug.info("NFL Board: Refreshing display games")
                self._refresh_display_games()

            debug.info(f"NFL Board: Have {len(self.current_display_items)} total items to display")

            # Check if we have anything to display
            if not self.current_display_items:
                debug.info("NFL Board: No content available, rendering message")
                self._render_no_content_available()
                return

            # Loop through all items and display each one
            for item in self.current_display_items:
                # Check for sleep event interruption before each item
                if self.sleepEvent.is_set():
                    debug.info("NFL Board: Sleep event set, interrupting display loop")
                    break

                # Render based on item type
                if isinstance(item, NFLGame):
                    debug.info(f"NFL Board: Displaying game {item.away_team.abbreviation} @ {item.home_team.abbreviation}")
                    if item.is_live:
                        self._render_live_game(item)
                    elif item.is_final:
                        self._render_completed_game(item)
                    else:
                        self._render_upcoming_game(item)
                elif isinstance(item, NFLTeam):
                    debug.info(f"NFL Board: Displaying team summary for {item.display_name}")
                    self._render_team_summary(item)
                else:
                    debug.warning(f"NFL Board: Unknown item type: {type(item)}, skipping")
                    continue

        except Exception as error:
            debug.error(f"NFL Board render error: {error}")
            self._render_error_display(str(error))

    def _setup_data_refresh_schedule(self):
        """Set up background data refresh using APScheduler."""
        scheduler = getattr(self.data, "scheduler", None)
        if not scheduler:
            debug.warning("NFL Board: No scheduler available, forcing immediate refresh")
            self._perform_scheduled_data_refresh()
            return

        # Only add job if it doesn't already exist
        if not scheduler.get_job(self._scheduled_job_id):
            scheduler.add_job(
                self._perform_full_data_refresh,
                "interval",
                seconds=self.config.refresh_seconds,
                id=self._scheduled_job_id,
                max_instances=1,
                replace_existing=True,
            )
            debug.info(f"NFL Board: Scheduled full data refresh every {self.config.refresh_seconds} seconds")
        else:
            debug.info("NFL Board: Data refresh job already scheduled")

    def _perform_basic_data_refresh(self):
        """
        Quick initial data refresh for immediate display.
        Fetches minimal data: teams list and today's games.
        """
        debug.info("NFL Board: Performing basic data refresh")

        try:
            # Create new data snapshot
            snapshot = NFLDataSnapshot()

            # Fetch all teams data (basic info only)
            all_teams = self.api_client.get_all_teams()
            if not all_teams:
                snapshot.add_error("Failed to fetch teams data")
                self.data.nfl_board_snapshot = snapshot
                return

            snapshot.all_teams = all_teams

            # Get favorite teams subset (basic info only for now)
            snapshot.favorite_teams = {
                team_id: team for team_id, team in all_teams.items()
                if team_id in self.config.team_ids
            }

            # Fetch today's games only (for quick display)
            today = datetime.now()
            snapshot.todays_games = self.api_client.get_scoreboard_for_date(today)

            # Identify live games
            snapshot.live_games = [game for game in snapshot.todays_games if game.is_live]

            # Get favorite team games from today only
            favorite_team_games = []
            for game in snapshot.todays_games:
                if any(game.involves_team(team_id) for team_id in self.config.team_ids):
                    favorite_team_games.append(game)

            snapshot.favorite_team_games = favorite_team_games

            # Store snapshot for board to use
            self.data.nfl_board_snapshot = snapshot

            debug.info(f"NFL Board: Basic data refresh complete - {len(snapshot.todays_games)} today, "
                      f"{len(snapshot.favorite_team_games)} favorite team games")

        except Exception as error:
            debug.error(f"NFL Board: Basic data refresh failed: {error}")
            # Store error snapshot
            error_snapshot = NFLDataSnapshot()
            error_snapshot.add_error(f"Basic data refresh failed: {error}")
            self.data.nfl_board_snapshot = error_snapshot

    def _perform_full_data_refresh(self):
        """
        Complete data refresh with all details.
        Fetches comprehensive data: detailed team records, schedules, yesterday's games, etc.
        """
        debug.info("NFL Board: Performing full data refresh")

        try:
            # Create new data snapshot
            snapshot = NFLDataSnapshot()

            # Fetch all teams data first
            all_teams = self.api_client.get_all_teams()
            if not all_teams:
                snapshot.add_error("Failed to fetch teams data")
                self.data.nfl_board_snapshot = snapshot
                return

            snapshot.all_teams = all_teams

            # Populate detailed information for ALL teams (not just favorites)
            # This gives us full records, standings info, etc.
            all_team_ids = list(all_teams.keys())
            detailed_count = self.api_client.populate_team_details(all_team_ids)
            debug.info(f"NFL Board: Loaded detailed data for {detailed_count} total teams")

            # Get favorite teams subset (now with detailed records)
            snapshot.favorite_teams = {
                team_id: team for team_id, team in all_teams.items()
                if team_id in self.config.team_ids
            }

            # Fetch today's games
            today = datetime.now()
            snapshot.todays_games = self.api_client.get_scoreboard_for_date(today)

            # Fetch yesterday's games
            yesterday = today - timedelta(days=1)
            snapshot.yesterdays_games = self.api_client.get_scoreboard_for_date(yesterday)

            # Identify live games
            snapshot.live_games = [game for game in snapshot.todays_games if game.is_live]

            # Get favorite team games from today and yesterday
            favorite_team_games = []
            all_recent_games = snapshot.todays_games + snapshot.yesterdays_games

            for game in all_recent_games:
                if any(game.involves_team(team_id) for team_id in self.config.team_ids):
                    favorite_team_games.append(game)

            snapshot.favorite_team_games = favorite_team_games

            # Get team schedules for favorite teams (for upcoming games)
            for team_id in self.config.team_ids:
                team_schedule = self.api_client.get_team_schedule(team_id)
                snapshot.team_schedules[team_id] = team_schedule

            # Store snapshot for board to use
            self.data.nfl_board_snapshot = snapshot

            debug.info(f"NFL Board: Full data refresh complete - {len(snapshot.todays_games)} today, "
                      f"{len(snapshot.yesterdays_games)} yesterday, {len(snapshot.favorite_team_games)} favorite team games")

        except Exception as error:
            debug.error(f"NFL Board: Full data refresh failed: {error}")
            # Store error snapshot
            error_snapshot = NFLDataSnapshot()
            error_snapshot.add_error(f"Full data refresh failed: {error}")
            self.data.nfl_board_snapshot = error_snapshot

    def _should_refresh_display_games(self) -> bool:
        """Check if we should refresh the list of games to display."""
        # Refresh every 30 seconds to catch live game changes
        time_since_refresh = datetime.now() - self.last_layout_refresh
        return time_since_refresh.total_seconds() >= 30

    def _refresh_display_games(self):
        """Update the unified list of items that should be displayed."""
        snapshot = getattr(self.data, "nfl_board_snapshot", None)
        if not snapshot or not snapshot.is_valid():
            debug.warning("NFL Board: No valid data snapshot available")
            self.current_display_items = []
            return

        # Get games to display based on configuration
        games_to_display = snapshot.get_games_for_display(
            favorite_team_ids=self.config.team_ids,
            show_all_games=self.config.show_all_games,
            cutoff_time=self.config.show_previous_games_until_time
        )

        # Additional filtering for previous games
        filtered_games = []
        for game in games_to_display:
            if self.config.should_show_previous_game(game):
                filtered_games.append(game)

        # Separate favorite team games from other games
        favorite_team_games = []
        other_games = []
        for game in filtered_games:
            if any(game.involves_team(team_id) for team_id in self.config.team_ids):
                favorite_team_games.append(game)
            else:
                other_games.append(game)

        # Determine which teams should show team summaries instead of games
        teams_with_games_today = set()
        for game in favorite_team_games:
            if game.date and game.date.date() == datetime.now().date():
                for team_id in self.config.team_ids:
                    if game.involves_team(team_id):
                        teams_with_games_today.add(team_id)

        # Build list of teams to show summaries for (favorite teams without games today)
        teams_for_summaries = []
        for team_id in self.config.team_ids:
            if team_id not in teams_with_games_today and team_id in snapshot.favorite_teams:
                teams_for_summaries.append(snapshot.favorite_teams[team_id])

        # Build unified display list: favorite games first, then other games, then team summaries
        display_items = []
        display_items.extend(favorite_team_games)  # Favorite team games first (highest priority)
        display_items.extend(other_games)          # Then other games if show_all_games is enabled
        display_items.extend(teams_for_summaries)  # Finally team summaries for teams without games

        self.current_display_items = display_items
        self.last_layout_refresh = datetime.now()

        debug.info(f"NFL Board: Updated unified display - {len(display_items)} total items ")
        debug.info(f"NFL Board: {len(favorite_team_games)} favorite games, {len(other_games)} other games, {len(teams_for_summaries)} team summaries")


    def _render_live_game(self, game: NFLGame):
        """Render a live game display."""
        debug.info(f"NFL Board: Rendering live game {game.away_team.abbreviation} @ {game.home_team.abbreviation}")

        self.matrix.clear()
        layout = self.get_board_layout('nfl_game')

        if not layout:
            self._render_fallback_game_display(game, "LIVE")
            return

        # Render team information
        self._render_team_display(layout, game, show_scores=True)

        # Render live game status
        live_status = self._format_live_game_status(game)
        if hasattr(layout, 'game_status'):
            self.matrix.draw_text_layout(layout.game_status, live_status)

        # Render to the display
        self.matrix.render()

        # Display the rendered content for configured duration
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_completed_game(self, game: NFLGame):
        """Render a completed game display."""
        debug.info(f"NFL Board: Rendering completed game {game.away_team.abbreviation} @ {game.home_team.abbreviation}")

        self.matrix.clear()
        layout = self.get_board_layout('nfl_game')

        if not layout:
            self._render_fallback_game_display(game, "FINAL")
            return

        # Render team information with final scores
        self._render_team_display(layout, game, show_scores=True)

        # Render final status
        if hasattr(layout, 'game_status'):
            self.matrix.draw_text_layout(layout.game_status, "FINAL")

        # Render to the display
        self.matrix.render()

        # Display the rendered content for configured duration
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_upcoming_game(self, game: NFLGame):
        """Render an upcoming game display."""
        debug.info(f"NFL Board: Rendering upcoming game {game.away_team.abbreviation} @ {game.home_team.abbreviation}")

        self.matrix.clear()
        layout = self.get_board_layout('nfl_game')

        if not layout:
            debug.warning(f"NFL Board: Couldn't find layout, falling back to default layout")
            self._render_fallback_game_display(game, self._format_game_datetime(game))
            return

        # Render team information with records instead of scores
        self._render_team_display(layout, game, show_scores=False)

        # Render game date/time
        if hasattr(layout, 'scheduled_date'):
            self.matrix.draw_text_layout(layout.scheduled_date, "TODAY")
        if hasattr(layout, "scheduled_time"):
            self.matrix.draw_text_layout(layout.scheduled_time, self._format_game_datetime(game, format_type="time_only"))

        # VS
        if hasattr(layout, "VS"):
            self.matrix.draw_text_layout(layout.VS, "VS")

        # Render to the display
        self.matrix.render()

        # Display the rendered content for configured duration
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_team_display(self, layout, game: NFLGame, show_scores: bool):
        """Render team information (logos, names, scores/records)."""
        # Render team logos
        if hasattr(layout, 'away_team_logo'):
            away_logo = self._get_team_logo(game.away_team)
            if away_logo:
                self._draw_logo(layout, "away_team_logo", away_logo, game.away_team.abbreviation)

        if hasattr(layout, 'home_team_logo'):
            home_logo = self._get_team_logo(game.home_team)
            if home_logo:
                self._draw_logo(layout, "home_team_logo", home_logo, game.home_team.abbreviation)

        # Render gradient - after logos but before other visuals
        self.matrix.draw_image([self.matrix.width/2,0], self.gradient, align="center")

        # Render team names
        # if hasattr(layout, 'away_team_name'):
        #     self.matrix.draw_text_layout(layout.away_team_name, game.away_team.abbreviation)

        # if hasattr(layout, 'home_team_name'):
        #     self.matrix.draw_text_layout(layout.home_team_name, game.home_team.abbreviation)

        # Render scores or records
        if show_scores:
            if hasattr(layout, 'away_team_score'):
                self.matrix.draw_text_layout(layout.away_team_score, str(game.away_score))
            if hasattr(layout, 'home_team_score'):
                self.matrix.draw_text_layout(layout.home_team_score, str(game.home_score))
        else:
            if hasattr(layout, 'away_team_score'):
                self.matrix.draw_text_layout(layout.away_team_score, game.away_team.record_text)
            if hasattr(layout, 'home_team_score'):
                self.matrix.draw_text_layout(layout.home_team_score, game.home_team.record_text)

    def _render_team_summary(self, team: NFLTeam):
        """Render team summary display showing team info, record, next/last games."""
        debug.info(f"NFL Board: Rendering team summary for {team.display_name}")
        debug.info(f"NFL Board: Team record: {team.record_text} (detailed: {team.has_detailed_record})")
        debug.info(f"NFL Board: Team colors: {team.color_primary}, {team.color_secondary}")

        if not team.has_detailed_record:
            debug.warning(f"NFL Board: Team {team.display_name} using basic data - detailed record not loaded")

        self.matrix.clear()
        layout = self.get_board_layout('nfl_team_summary')

        if not layout:
            debug.info("NFL Board: No team summary layout found, using fallback")
            self._render_fallback_team_summary(team)
            return

        debug.info("NFL Board: Using team summary layout")

        # Get team's schedule data for next/last game info
        snapshot = getattr(self.data, "nfl_board_snapshot", None)
        team_schedule = []
        if snapshot and team.team_id in snapshot.team_schedules:
            team_schedule = snapshot.team_schedules[team.team_id]

        # Render team logo
        if hasattr(layout, 'team_logo'):
            team_logo = self._get_team_logo(team)
            if team_logo:
                #self.matrix.draw_image_layout(layout.team_logo, team_logo)
                self._draw_logo(layout, 'team_logo', team_logo, team.abbreviation)

        # Render team name with team colors
        if hasattr(layout, 'team_name'):
            self.matrix.draw_text_layout(
                layout.team_name,
                team.display_name,
                fillColor=team.color_primary,
                backgroundColor=team.color_secondary
            )

        # Render record
        if hasattr(layout, 'record_header'):
            debug.info("NFL Board: Rendering record header")
            self.matrix.draw_text_layout(layout.record_header, "RECORD:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
        if hasattr(layout, 'record'):
            # Use record_text property which has safe fallbacks
            #record_display = team.record_summary if team.record_summary else team.record_text
            debug.info(f"NFL Board: Rendering record: {team.record_text}")
            self._draw_text(layout, "record", team.record_text)
        if hasattr(layout, 'record_comment') and team.record_comment:
            debug.info(f"NFL Board: Rendering record comment: {team.record_comment}")
            self._draw_text(layout, "record_comment", team.record_comment)

        # Render next game information
        next_game = self._get_next_game_for_team(team.team_id, team_schedule)
        if hasattr(layout, 'next_game_header'):
            self.matrix.draw_text_layout(layout.next_game_header, "NEXT GAME:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
        if hasattr(layout, 'next_game'):
            next_game_text = self._format_next_game_display(next_game, team.team_id)
            self.matrix.draw_text_layout(layout.next_game, next_game_text)

        # Render last game information
        last_game = self._get_last_game_for_team(team.team_id, team_schedule)
        if hasattr(layout, 'last_game_header'):
            self.matrix.draw_text_layout(layout.last_game_header, "LAST GAME:", fillColor=team.color_primary, backgroundColor=team.color_secondary)
        if hasattr(layout, 'last_game_result'):
            last_game_text = self._format_last_game_display(last_game, team.team_id)
            self.matrix.draw_text_layout(layout.last_game_result, last_game_text)

        # Render to the display
        self.matrix.render()

        # Display the rendered content for configured duration
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_no_content_available(self):
        """Render display when no games or team summaries are available."""
        debug.info("NFL Board: Rendering no content available message")

        self.matrix.clear()
        layout = self.get_board_layout('nfl_game')

        if layout and hasattr(layout, 'game_status'):
            self.matrix.draw_text_layout(layout.game_status, "No NFL Content")
        else:
            # Fallback to centered text
            font = self.data.config.layout.font
            self.matrix.draw_text_centered(self.display_height // 2, "No NFL Content", font)

        # Render to the display
        self.matrix.render()

        # Display the rendered content for configured duration
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_error_display(self, error_message: str):
        """Render error message display."""
        debug.info(f"NFL Board: Rendering error display: {error_message}")

        self.matrix.clear()
        layout = self.get_board_layout('nfl')

        if layout and hasattr(layout, 'game_status'):
            self.matrix.draw_text_layout(layout.game_status, "NFL Error")
        else:
            # Fallback to centered text
            font = self.data.config.layout.font
            self.matrix.draw_text_centered(self.display_height // 2, "NFL Error", font)

        # Render to the display
        self.matrix.render()

        # Display the rendered content for configured duration
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_fallback_game_display(self, game: NFLGame, status_text: str):
        """Render game information when no layout is available."""
        font = self.data.config.layout.font

        # Simple text display
        away_text = f"{game.away_team.abbreviation} {game.away_score}"
        home_text = f"{game.home_team.abbreviation} {game.home_score}"

        self.matrix.draw_text_centered(15, away_text, font)
        self.matrix.draw_text_centered(25, "vs", font)
        self.matrix.draw_text_centered(35, home_text, font)
        self.matrix.draw_text_centered(50, status_text, font)

        # Render to the display
        self.matrix.render()

        # Display the rendered content for configured duration
        self.sleepEvent.wait(self.config.display_seconds)

    def _get_team_logo(self, team: NFLTeam) -> Optional[Image.Image]:
        """Get team logo image with caching and automatic downloading."""
        cache_key = f"{team.abbreviation}_logo"

        if cache_key in self.logo_cache:
            return self.logo_cache[cache_key]

        try:
            # First try the API client's logo path resolution and download functionality
            logo_path = self.api_client.get_team_logo_path(team, size=128, download_if_missing=True)

            if logo_path and logo_path.exists():
                logo_image = Image.open(logo_path)
                self.logo_cache[cache_key] = logo_image
                debug.log(f"NFL Board: Loaded logo for {team.abbreviation} from {logo_path}")
                return logo_image

            debug.info(f"NFL Board: No logo available for {team.abbreviation} (URL: {team.logo_url})")

        except Exception as error:
            debug.error(f"NFL Board: Failed to load logo for {team.abbreviation}: {error}")

        return None
    
    def _draw_logo(self, layout, element_name: str, logo: Image, team_abbreviation: str) -> None:
        """
        Draw a team logo using element-specific offsets.

        Args:
            layout: Layout object containing the logo element
            element_name: Name of the logo element (also used as offset key)
            logo_path: Path to the logo image file
            team_abbreviation: Team abbreviation for offset lookup
        """
        if not hasattr(layout, element_name) or not logo:
            return

        # Use element_name as the offset key
        offsets = self._get_logo_offsets(team_abbreviation, element_name)

        zoom = float(offsets.get("zoom", 1.0))
        offset_x, offset_y = offsets.get("offset", (0, 0))

        # Scale logo to appropriate size
        max_dimension = 64 if self.matrix.height >= 48 else min(32, self.matrix.height)

        if max(logo.size) > max_dimension:
            logo.thumbnail((max_dimension, max_dimension), self._thumbnail_filter())

        # Apply zoom if needed
        if zoom != 1.0:
            w, h = logo.size
            zoomed = logo.resize(
                (max(1, int(round(w * zoom))), max(1, int(round(h * zoom)))),
                self._thumbnail_filter(),
            )
            logo = zoomed

        # Apply offset to layout element
        element = getattr(layout, element_name).__copy__()
        x, y = element.position
        element.position = (x + offset_x, y + offset_y)

        self.matrix.draw_image_layout(element, logo)

    @staticmethod
    def _thumbnail_filter():
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
        if resampling is None:
            resampling = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
        return resampling

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
    
    def _load_logo_offsets(self) -> Dict[str, Dict[str, any]]:
        """Load logo positioning offsets from configuration file."""
        try:
            offsets_path = self._get_board_directory() / "logo_offsets.json"

            if offsets_path.exists():
                with offsets_path.open() as file:
                    raw_offsets = json.load(file)

                # Process offsets with defaults
                default_offset = raw_offsets.get("_default", {"zoom": 1.0, "offset": (0, 0)})
                processed_offsets = {}

                for key, value in raw_offsets.items():
                    if key != "_default":
                        processed_offsets[key.upper()] = {**default_offset, **value}

                processed_offsets["_default"] = default_offset
                return processed_offsets

        except Exception as error:
            debug.error(f"NFL Board: Failed to load logo offsets: {error}")

        return {"_default": {"zoom": 1.0, "offset": (0, 0)}}

    def _format_live_game_status(self, game: NFLGame) -> str:
        """Format status text for live games."""
        if game.quarter and game.time_remaining:
            return f"Q{game.quarter} {game.time_remaining}"
        elif game.quarter:
            return f"Q{game.quarter}"
        else:
            return "LIVE"

    def _format_game_datetime(self, game: NFLGame, format_type: str = "full") -> str:
        """Format game date and time for display."""
        if not game.date:
            return "TBD"
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

    def _get_next_game_for_team(self, team_id: str, team_schedule: List[NFLGame]) -> Optional[NFLGame]:
        """Find the next upcoming game for a specific team."""
        now = datetime.now(timezone.utc)  # Make timezone-aware
        upcoming_games = []

        for game in team_schedule:
            if (game.involves_team(team_id) and
                game.date and
                game.date > now and
                not game.is_final):
                upcoming_games.append(game)

        if upcoming_games:
            # Sort by date and return the earliest
            upcoming_games.sort(key=lambda g: g.date or datetime.max.replace(tzinfo=timezone.utc))
            return upcoming_games[0]

        return None

    def _get_last_game_for_team(self, team_id: str, team_schedule: List[NFLGame]) -> Optional[NFLGame]:
        """Find the most recent completed game for a specific team."""
        now = datetime.now(timezone.utc)  # Make timezone-aware
        completed_games = []

        for game in team_schedule:
            if (game.involves_team(team_id) and
                game.date and
                game.date < now and
                game.is_final):
                completed_games.append(game)

        if completed_games:
            # Sort by date and return the most recent
            completed_games.sort(key=lambda g: g.date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return completed_games[0]

        return None

    def _format_next_game_display(self, game: Optional[NFLGame], team_id: str) -> str:
        """Format next game information for display."""
        if not game:
            return "---"

        opponent = game.get_opposing_team(team_id)
        if not opponent:
            return "TBD"

        game_time = self._format_game_datetime(game)

        # Determine if home or away
        if game.home_team.team_id == team_id:
            opponent_text = f"vs {opponent.abbreviation}"
        else:
            opponent_text = f"@ {opponent.abbreviation}"

        return f"{game_time} {opponent_text}".upper()

    def _format_last_game_display(self, game: Optional[NFLGame], team_id: str) -> str:
        """Format last game result for display."""
        if not game:
            return "---"

        opponent = game.get_opposing_team(team_id)
        if not opponent:
            return "TBD"

        # Determine result and format
        if game.home_team.team_id == team_id:
            team_score = game.home_score
            opponent_score = game.away_score
            opponent_text = f"vs {opponent.abbreviation}"
        else:
            team_score = game.away_score
            opponent_score = game.home_score
            opponent_text = f"@ {opponent.abbreviation}"

        # Format result
        if team_score > opponent_score:
            result = "W"
        elif team_score < opponent_score:
            result = "L"
        else:
            result = "T"

        return f"{result} {team_score}-{opponent_score} {opponent_text}".upper()

    def _render_fallback_team_summary(self, team: NFLTeam):
        """Render team summary when no layout is available."""
        debug.info(f"NFL Board: Rendering fallback team summary for {team.display_name}")

        font = self.data.config.layout.font
        debug.info(f"NFL Board: Using font: {font}")

        # Simple text display
        debug.info("NFL Board: Drawing team name")
        self.matrix.draw_text_centered(10, team.display_name, font)

        debug.info(f"NFL Board: Drawing record: {team.record_text}")
        self.matrix.draw_text_centered(25, f"Record: {team.record_text}", font)

        debug.info("NFL Board: Drawing summary label")
        self.matrix.draw_text_centered(40, "Team Summary", font)

        debug.info("NFL Board: Calling matrix.render()")
        # Render to the display
        self.matrix.render()

        debug.info(f"NFL Board: Waiting {self.config.display_seconds} seconds")
        # Display the rendered content for configured duration
        self.sleepEvent.wait(self.config.display_seconds)

        debug.info("NFL Board: Fallback team summary complete")

    def _draw_text(self, layout, element_name: str, text: str) -> None:
        """
        Helper method to draw text on layout elements, similar to old implementation.
        """
        if hasattr(layout, element_name):
            element = getattr(layout, element_name)
            self.matrix.draw_text_layout(element, text)

    def _load_gradient(self) -> Image.Image:
        """Load appropriate gradient image for current matrix size."""
        if self.matrix.height >= 48:
            return Image.open(get_file('assets/images/128x64_scoreboard_center_gradient.png'))
        else:
            return Image.open(get_file('assets/images/64x32_scoreboard_center_gradient.png'))
        
    def _get_board_directory(self) -> Path:
        """Get the directory path for this board plugin."""
        return Path(__file__).parent

    def cleanup(self):
        """Clean up resources when board is unloaded."""
        debug.info("NFL Board: Cleaning up resources")

        # Clear caches and display state
        self.logo_cache.clear()
        self.current_display_items.clear()

        # Remove scheduled job if it exists
        scheduler = getattr(self.data, "scheduler", None)
        if scheduler and scheduler.get_job(self._scheduled_job_id):
            scheduler.remove_job(self._scheduled_job_id)
            debug.info("NFL Board: Removed scheduled data refresh job")