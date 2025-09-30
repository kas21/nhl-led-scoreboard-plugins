"""
NFL Board Data Management - Clean Implementation
Handles API calls and data processing using APScheduler for background refresh.
"""

import logging
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from pathlib import Path
from PIL import Image
import io

debug = logging.getLogger("scoreboard")

def parse_espn_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ESPN datetime strings which typically end with Z."""
    if not value:
        return None
    try:
        # ESPN dates are UTC with "Z", convert to format that works with fromisoformat
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        debug.error(f"NFL Board: Could not parse datetime '{value}'")
        return None


def safe_int_conversion(value: Optional[str]) -> Optional[int]:
    """Safely convert ESPN score strings to integers."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_get_score_value(score_data) -> int:
    """Safely extract score value from various ESPN API formats."""
    if not score_data:
        return 0

    # Handle string format (direct score value)
    if isinstance(score_data, str):
        return safe_int_conversion(score_data) or 0

    # Handle dict format ({"value": "14"})
    if isinstance(score_data, dict) and "value" in score_data:
        return safe_int_conversion(score_data.get("value")) or 0

    return 0


@dataclass
class NFLTeam:
    """Represents an NFL team with all relevant information."""
    team_id: str
    name: str
    abbreviation: str
    display_name: str
    location: str
    color_primary: tuple  # RGB tuple like (255, 255, 255)
    color_secondary: tuple  # RGB tuple like (0, 0, 0)
    logo_url: Optional[str] = None
    record_wins: int = 0
    record_losses: int = 0
    record_ties: int = 0
    record_summary: str = ""
    record_comment: Optional[str] = "---"

    @property
    def has_detailed_record(self) -> bool:
        """Check if this team has detailed record information loaded."""
        return bool(self.record_summary or self.record_wins > 0 or self.record_losses > 0)

    @property
    def record_text(self) -> str:
        """Format team record for display with safe fallback."""
        # Use detailed record if available
        if self.record_summary:
            return self.record_summary

        # Fallback to basic wins/losses if we have that data
        if self.has_detailed_record:
            if self.record_ties > 0:
                return f"{self.record_wins}-{self.record_losses}-{self.record_ties}"
            return f"{self.record_wins}-{self.record_losses}"

        # No record data available
        return "---"


@dataclass
class NFLGame:
    """Represents an NFL game with complete information."""
    game_id: str
    date: Optional[datetime]
    home_team: NFLTeam
    away_team: NFLTeam
    home_score: int = 0
    away_score: int = 0
    status_state: str = "pre"
    status_detail: str = "Scheduled"
    quarter: Optional[str] = None
    time_remaining: Optional[str] = None
    is_final: bool = False
    is_live: bool = False
    venue: Optional[str] = None

    def involves_team(self, team_id: str) -> bool:
        """Check if this game involves the specified team."""
        return self.home_team.team_id == team_id or self.away_team.team_id == team_id

    def get_opposing_team(self, team_id: str) -> Optional[NFLTeam]:
        """Get the opposing team for the specified team ID."""
        if self.home_team.team_id == team_id:
            return self.away_team
        elif self.away_team.team_id == team_id:
            return self.home_team
        return None

    @property
    def winning_team(self) -> Optional[NFLTeam]:
        """Get the team that is currently winning."""
        if self.home_score > self.away_score:
            return self.home_team
        elif self.away_score > self.home_score:
            return self.away_team
        return None


class NFLApiClient:
    """
    Handles all NFL API communication with ESPN endpoints.
    Provides clean methods for different data needs.
    """

    def __init__(self, logo_cache_directory: Optional[Path] = None):
        self.base_url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
        self.logo_cache_directory = logo_cache_directory or Path("assets/logos/nfl")
        self.teams_cache: Dict[str, NFLTeam] = {}
        self.last_teams_fetch: Optional[datetime] = None

        # Ensure logo cache directory exists
        self.logo_cache_directory.mkdir(parents=True, exist_ok=True)

    def get_scoreboard_for_date(self, date: datetime) -> List[NFLGame]:
        """
        Get all games for a specific date using ESPN scoreboard endpoint.
        Date format: YYYYMMDD
        """
        date_string = date.strftime("%Y%m%d")
        url = f"{self.base_url}/scoreboard?dates={date_string}"

        debug.debug(f"NFL Board: Fetching scoreboard for {date_string}")

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            games = []
            events = data.get("events", [])

            for event in events:
                game = self._parse_game_from_event(event)
                if game:
                    games.append(game)

            debug.debug(f"NFL Board: Found {len(games)} games for {date_string}")
            return games

        except Exception as exc:
            debug.error(f"NFL Board: Failed to fetch scoreboard for {date_string}: {exc}")
            return []

    def get_current_scoreboard(self) -> List[NFLGame]:
        """Get current/today's games."""
        return self.get_scoreboard_for_date(datetime.now())

    def get_all_teams(self) -> Dict[str, NFLTeam]:
        """
        Get basic NFL teams information (no detailed records).
        Use get_team_details() to populate full details for specific teams.
        """
        # Use cached data if less than 1 hour old
        if (self.teams_cache and self.last_teams_fetch and
            datetime.now() - self.last_teams_fetch < timedelta(hours=1)):
            return self.teams_cache

        try:
            url = f"{self.base_url}/teams"
            debug.info(f"NFL Board: Fetching basic teams data")

            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            teams = {}
            sports = data.get("sports", [])
            if sports:
                leagues = sports[0].get("leagues", [])
                if leagues:
                    team_list = leagues[0].get("teams", [])

                    for team_item in team_list:
                        team_data = team_item.get("team", {})
                        team = self._parse_basic_team_data(team_data)
                        if team:
                            teams[team.team_id] = team

            self.teams_cache = teams
            self.last_teams_fetch = datetime.now()

            debug.info(f"NFL Board: Cached {len(teams)} basic teams")
            return teams

        except Exception as exc:
            debug.error(f"NFL Board: Failed to fetch teams: {exc}")
            return self.teams_cache

    def get_team_schedule(self, team_id: str) -> List[NFLGame]:
        """
        Get schedule for a specific team.
        Returns recent and upcoming games.
        """
        try:
            url = f"{self.base_url}/teams/{team_id}/schedule"
            debug.debug(f"NFL Board: Fetching schedule for team {team_id}")

            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            games = []
            events = data.get("events", [])

            for event in events:
                game = self._parse_game_from_event(event)
                if game:
                    games.append(game)

            debug.debug(f"NFL Board: Found {len(games)} scheduled games for team {team_id}")
            return games

        except Exception as exc:
            debug.error(f"NFL Board: Failed to fetch schedule for team {team_id}: {exc}")
            return []

    def _parse_basic_team_data(self, team_data: Dict[str, Any]) -> Optional[NFLTeam]:
        """Parse basic team information from ESPN /teams endpoint (no detailed records)."""
        try:
            team_id = team_data.get("id")
            if not team_id:
                return None

            # Extract logo URL
            logo_url = None
            logos = team_data.get("logos", [])
            if logos:
                logo_url = logos[0].get("href")

            # Convert colors to RGB tuples
            color_primary = self._hex_to_rgb(team_data.get("color", "000000"))
            color_secondary = self._hex_to_rgb(team_data.get("alternateColor", "FFFFFF"))

            return NFLTeam(
                team_id=team_id,
                name=team_data.get("name", ""),
                abbreviation=team_data.get("abbreviation", ""),
                display_name=team_data.get("displayName", ""),
                location=team_data.get("location", ""),
                color_primary=color_primary,
                color_secondary=color_secondary,
                logo_url=logo_url,
                # Note: No detailed record data - use get_team_details() to populate
                record_wins=0,
                record_losses=0,
                record_ties=0,
                record_summary="",
                record_comment="---"
            )

        except Exception as exc:
            debug.error(f"NFL Board: Failed to parse basic team data: {exc}")
            return None

    def _parse_team_data(self, team_data: Dict[str, Any]) -> Optional[NFLTeam]:
        """Parse team information from ESPN API response."""
        try:
            team_id = team_data.get("id")
            if not team_id:
                return None

            # Extract logo URL
            logo_url = None
            logos = team_data.get("logos", [])
            if logos:
                logo_url = logos[0].get("href")

            # Extract team record
            wins = losses = ties = 0
            record_summary = ""
            # The record object has a list of record types
            # The first item in the list should be the TOTAL record 
            record_items = team_data.get("record", {}).get("items", [])
            #debug.info(record_items)
            if record_items:
                # Get the summary from first record item
                summary = record_items[0].get("summary")
                if summary:
                    record_summary = summary

                # Also extract individual stats for our internal tracking
                stats = record_items[0].get("stats", [])
                for stat in stats:
                    stat_name = stat.get("name")
                    if stat_name == "wins":
                        wins = int(stat.get("value", 0))
                    elif stat_name == "losses":
                        losses = int(stat.get("value", 0))
                    elif stat_name == "ties":
                        ties = int(stat.get("value", 0))
                #debug.info(f"RECORD!!! {wins}-{losses}-{ties}")

            # Extract standing summary for record_comment
            record_comment = team_data.get("standingSummary")

            # Convert colors to RGB tuples (old implementation expected tuples)
            color_primary = self._hex_to_rgb(team_data.get("color", "000000"))
            color_secondary = self._hex_to_rgb(team_data.get("alternateColor", "FFFFFF"))

            return NFLTeam(
                team_id=team_id,
                name=team_data.get("name", ""),
                abbreviation=team_data.get("abbreviation", ""),
                display_name=team_data.get("displayName", ""),
                location=team_data.get("location", ""),
                color_primary=color_primary,
                color_secondary=color_secondary,
                logo_url=logo_url,
                record_wins=wins,
                record_losses=losses,
                record_ties=ties,
                record_summary=record_summary,
                record_comment=record_comment
            )

        except Exception as exc:
            debug.error(f"NFL Board: Failed to parse team data: {exc}")
            return None

    def _parse_game_from_event(self, event_data: Dict[str, Any]) -> Optional[NFLGame]:
        """Parse game information from ESPN event data."""
        try:
            game_id = event_data.get("id", "")

            # Parse game date
            game_date = parse_espn_datetime(event_data.get("date"))

            # Parse competitions (should be one for NFL)
            competitions = event_data.get("competitions", [])
            if not competitions:
                return None

            competition = competitions[0]
            competitors = competition.get("competitors", [])

            if len(competitors) < 2:
                return None

            # Find home and away teams
            home_competitor = None
            away_competitor = None

            for competitor in competitors:
                if competitor.get("homeAway") == "home":
                    home_competitor = competitor
                elif competitor.get("homeAway") == "away":
                    away_competitor = competitor

            if not home_competitor or not away_competitor:
                return None

            # Parse team data from competitors
            home_team = self._parse_competitor_team(home_competitor)
            away_team = self._parse_competitor_team(away_competitor)

            if not home_team or not away_team:
                return None

            # Parse scores safely (handles both string and dict formats)
            home_score_data = home_competitor.get("score")
            away_score_data = away_competitor.get("score")

            home_score = safe_get_score_value(home_score_data)
            away_score = safe_get_score_value(away_score_data)

            # Parse game status
            status = competition.get("status", {})
            status_type = status.get("type", {})
            status_state = status_type.get("state", "pre")
            status_detail = status_type.get("shortDetail", "Scheduled")

            is_final = status_type.get("completed", False)
            is_live = status_state == "in"

            # Parse live game details
            quarter = None
            time_remaining = None
            if is_live:
                quarter = str(status.get("period", ""))
                time_remaining = status.get("displayClock")

            # Parse venue
            venue = None
            venue_data = competition.get("venue")
            if venue_data:
                venue = venue_data.get("fullName")

            return NFLGame(
                game_id=game_id,
                date=game_date,
                home_team=home_team,
                away_team=away_team,
                home_score=home_score,
                away_score=away_score,
                status_state=status_state,
                status_detail=status_detail,
                quarter=quarter,
                time_remaining=time_remaining,
                is_final=is_final,
                is_live=is_live,
                venue=venue
            )

        except Exception as exc:
            debug.error(f"NFL Board: Failed to parse game data: {exc}")
            import traceback
            debug.error(traceback.print_exc())
            return None

    def _parse_competitor_team(self, competitor: Dict[str, Any]) -> Optional[NFLTeam]:
        """Parse team data from competitor information."""
        team_data = competitor.get("team", {})
        team_id = team_data.get("id")

        if not team_id:
            return None

        # Check if we have this team in cache
        if team_id in self.teams_cache:
            return self.teams_cache[team_id]

        # Create basic team info from competitor data
        logo_url = None
        logos = team_data.get("logos", [])
        if logos:
            logo_url = logos[0].get("href")

        return NFLTeam(
            team_id=team_id,
            name=team_data.get("name", ""),
            abbreviation=team_data.get("abbreviation", ""),
            display_name=team_data.get("displayName", ""),
            location=team_data.get("location", ""),
            color_primary=(255, 255, 255),  # Default white for competitor data
            color_secondary=(0, 0, 0),      # Default black for competitor data
            logo_url=logo_url
        )

    def get_team_details(self, team_id: str) -> bool:
        """
        Fetch detailed team information and update the cached team.
        Returns True if successful, False otherwise.
        """
        try:
            url = f"{self.base_url}/teams/{team_id}"
            debug.debug(f"NFL Board: Fetching detailed data for team {team_id}")

            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            detailed_team = self._parse_team_data(data.get("team", {}))
            if detailed_team and team_id in self.teams_cache:
                # Update the cached team with detailed information
                self.teams_cache[team_id] = detailed_team
                debug.debug(f"NFL Board: Updated team {team_id} with detailed record data")
                return True
            else:
                debug.warning(f"NFL Board: Failed to get detailed data for team {team_id}")
                return False

        except Exception as exc:
            debug.error(f"NFL Board: Failed to fetch team details for {team_id}: {exc}")
            return False

    def populate_team_details(self, team_ids: List[str]) -> int:
        """
        Populate detailed information for specified teams.
        Returns count of successfully updated teams.
        """
        success_count = 0
        debug.info(f"NFL Board: Populating details for {len(team_ids)} teams")

        for team_id in team_ids:
            if self.get_team_details(team_id):
                success_count += 1

        debug.info(f"NFL Board: Successfully populated details for {success_count}/{len(team_ids)} teams")
        return success_count

    def _hex_to_rgb(self, hex_color: str) -> tuple:
        """Convert hex color to RGB tuple."""
        try:
            # Strip leading '#' if present
            hex_color = hex_color.lstrip('#')
            # Convert to RGB tuple
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except (ValueError, TypeError):
            return (255, 255, 255)  # Default to white

    def download_team_logo(self, team: NFLTeam, size: int = 64) -> Optional[Path]:
        """
        Download and cache a team logo as a PNG file.

        Args:
            team: NFLTeam object with logo_url
            size: Target size for the logo (default 64px)

        Returns:
            Path to cached logo file, or None if download failed
        """
        if not team.logo_url:
            debug.warning(f"NFL Board: No logo URL for team {team.abbreviation}")
            return None

        # Generate cache filename
        cache_filename = f"{team.abbreviation.lower()}_{size}px.png"
        cache_path = self.logo_cache_directory / cache_filename

        # Return existing cached file if it exists
        if cache_path.exists():
            return cache_path

        try:
            debug.debug(f"NFL Board: Downloading logo for {team.abbreviation} from {team.logo_url}")

            # Download the logo
            response = requests.get(team.logo_url, timeout=10)
            response.raise_for_status()

            # Open and resize the image
            image = Image.open(io.BytesIO(response.content))

            # Convert to RGBA if not already (for transparency support)
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            # Trim Transparency
            bbox = image.getbbox()
            image = image.crop(bbox)
            # Keep aspect ratio but ensure the longest edge is equal to size.
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
            if resampling is None:
                resampling = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
            image.thumbnail((size, size), resampling)
            

            # Resize to target size while maintaining aspect ratio
            #image.thumbnail((size, size), Image.Resampling.LANCZOS)

            # Create a square canvas and center the logo
            square_image = Image.new('RGBA', (size, size), (255, 255, 255, 0))

            # Calculate position to center the logo
            x = (size - image.width) // 2
            y = (size - image.height) // 2

            square_image.paste(image, (x, y), image)

            # Save as PNG
            square_image.save(cache_path, 'PNG')

            debug.debug(f"NFL Board: Cached logo for {team.abbreviation} at {cache_path}")
            return cache_path

        except Exception as exc:
            debug.error(f"NFL Board: Failed to download logo for {team.abbreviation}: {exc}")
            return None

    def get_team_logo_path(self, team: NFLTeam, size: int = 128, download_if_missing: bool = True) -> Optional[Path]:
        """
        Get the local path to a team's logo, optionally downloading if missing.

        Args:
            team: NFLTeam object
            size: Target logo size (default 64px)
            download_if_missing: Whether to download the logo if not cached

        Returns:
            Path to logo file, or None if not available
        """
        cache_filename = f"{team.abbreviation.lower()}_{size}px.png"
        cache_path = self.logo_cache_directory / cache_filename

        # Return existing cached file
        if cache_path.exists():
            return cache_path

        # Download if requested and URL available
        if download_if_missing and team.logo_url:
            return self.download_team_logo(team, size)

        return None

    def preload_logos_for_teams(self, teams: List[NFLTeam], size: int = 64) -> int:
        """
        Preload logos for a list of teams.

        Args:
            teams: List of NFLTeam objects
            size: Target logo size (default 64px)

        Returns:
            Number of logos successfully downloaded/cached
        """
        success_count = 0

        for team in teams:
            logo_path = self.get_team_logo_path(team, size, download_if_missing=True)
            if logo_path:
                success_count += 1

        debug.debug(f"NFL Board: Preloaded {success_count}/{len(teams)} team logos")
        return success_count


class NFLDataSnapshot:
    """
    Pure data container for NFL data that gets stored on the scheduler refresh.
    Contains only data storage, no business logic.
    """

    def __init__(self):
        self.timestamp = datetime.now()
        self.error_message: Optional[str] = None

        # Teams data
        self.all_teams: Dict[str, NFLTeam] = {}
        self.favorite_teams: Dict[str, NFLTeam] = {}

        # Games data organized by category
        self.todays_games: List[NFLGame] = []
        self.yesterdays_games: List[NFLGame] = []
        self.favorite_team_games: List[NFLGame] = []
        self.live_games: List[NFLGame] = []

        # Team schedules for favorite teams
        self.team_schedules: Dict[str, List[NFLGame]] = {}