"""
Holiday Countdown board module implementation.
"""
from boards.base_board import BoardBase
from . import __version__, __description__, __board_name__
import datetime
from data.data import Data
from renderer.matrix import Matrix
import debug

import csv
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Iterable

from holidays import country_holidays
from holidays.constants import PUBLIC, GOVERNMENT, UNOFFICIAL
from PIL import Image


# ---- Data classes ------------------------------------------------------------

@dataclass(frozen=True)
class HolidayTheme:
    fg: str
    bg: str
    image: Optional[str] = None


# ---- Helpers -----------------------------------------------------------------

def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())

def _read_json(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _read_custom_csv(path: str) -> list[dict]:
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _parse_custom_date(token: str, today: date) -> date:
    # Supports YYYY-MM-DD or MM-DD (recurring next occurrence)
    if len(token) == 10:
        return datetime.strptime(token, "%Y-%m-%d").date()
    mm, dd = map(int, token.split("-"))
    candidate = date(today.year, mm, dd)
    return candidate if candidate >= today else date(today.year + 1, mm, dd)

def load_themes(themes_json_path: str) -> dict[str, HolidayTheme]:
    raw = _read_json(themes_json_path)
    themes: dict[str, HolidayTheme] = {}
    for k, v in raw.items():
        key = _normalize_name(k)
        themes[key] = HolidayTheme(
            fg=v.get("fg", "#FFFFFF"),
            bg=v.get("bg", "#000000"),
            image=v.get("image"),
        )
    # Ensure default exists
    themes.setdefault("default", HolidayTheme("#FFFFFF", "#000000", None))
    return themes

def load_custom_holidays(csv_path: str, today: date) -> list[tuple[date, str, dict]]:
    out: list[tuple[date, str, dict]] = []
    for row in _read_custom_csv(csv_path):
        name = (row.get("name") or "").strip()
        token = (row.get("date") or "").strip()  # "YYYY-MM-DD" or "MM-DD"
        if not name or not token:
            continue
        dt = _parse_custom_date(token, today)
        meta = {
            "image": (row.get("image") or None),
            "fg": (row.get("fg") or None),
            "bg": (row.get("bg") or None),
        }
        out.append((dt, name, meta))
    return out

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# ---- Main class --------------------------------------------------------------

class HolidayCountdownBoard(BoardBase):
    """
    The **Holiday Countdown Board** displays upcoming holidays on an LED matrix with customizable colors and images.
    
    ## Features

    - Displays days until the next holiday within a configurable horizon.
    - Supports country/subdivision selection via the `holidays` library.
    - Ignore specific holidays you don’t want to show.
    - Add **custom holidays** (recurring or fixed-date).
    - Apply per-holiday **themes** (foreground color, background color, image).
    - Default theme fallback ensures all holidays have consistent styling.
    """
    
    def __init__(self, data, matrix, sleepEvent):
        super().__init__(data, matrix, sleepEvent)
        
        # Board metadata from package
        self.board_name = __board_name__
        self.board_version = __version__
        self.board_description = __description__
        
        # Get configuration values with defaults
        self.country_code = self.board_config.get("country_code", "US")
        self.subdiv = self.board_config.get("subdiv", "NY")
        self.categories = self.board_config.get("catgegories", "")
        self.ignored_holidays = self.board_config.get("ignored_holidays", "")
        self.horizon_days = self.board_config.get("horizon_days", 90)

        # Resolve paths relative to the plugin directory
        self.board_dir = self._get_board_directory()
        self.themes_path = self._resolve_path(self.board_config.get("themes_path", "holiday_themes.json"))
        self.custom_holidays_path = self._resolve_path(self.board_config.get("custom_holidays_path", "custom_holidays.csv"))
        
        # Access standard application config
        self.font = data.config.layout.font
        self.font_large = data.config.layout.font_large
        self.team_colors = self.data.config.team_colors

        # Set some additional class properties
        self.rows = self.matrix.height
        self.cols = self.matrix.width

        # Load user data
        self.themes = load_themes(self.themes_path)

        # Date-dependent data will be computed fresh in render()
        self._last_computed_date = None
        self.today = None
        self.custom_rows = []
        self.upcoming_holidays: list[tuple[date, str]] = []

        # Image cache
        self._image_cache: dict[str, Image.Image] = {}

    def _get_board_directory(self):
        """Get the absolute path to this board's directory."""
        import inspect
        board_file = inspect.getfile(self.__class__)
        return os.path.dirname(os.path.abspath(board_file))

    def _resolve_path(self, path):
        """Resolve a path relative to the board directory."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.board_dir, path)

    # -------- Rendering --------

    def render(self):
        # Refresh date-dependent data if date has changed
        today = date.today()
        if self._last_computed_date != today:
            self.today = today
            self.custom_rows = load_custom_holidays(self.custom_holidays_path, self.today)
            self.upcoming_holidays = self._compute_upcoming()
            self._last_computed_date = today

        self.matrix.clear()

        layout = self.get_board_layout("holiday_countdown")

        black_gradiant = Image.open(f'assets/images/{self.cols}x{self.rows}_scoreboard_center_gradient.png')

        for dt, name in self.upcoming_holidays:
            if name in self.ignored_holidays:
                continue
            
            self.matrix.clear()

            days_til = (dt - self.today).days
            csv_meta = self._get_csv_meta(dt, name)
            theme = self._pick_theme(name, csv_meta)

            # Background - this looked bad so commenting out
            # bg_rgb = _hex_to_rgb(theme.bg)
            # self.matrix.draw_rectangle((0,0), (self.cols, self.rows), bg_rgb)

            # Image
            if theme.image:
                img = self._open_image(theme.image)
                # Resize holiday image for 64x32 matrix
                if (self.rows < 64):
                    new_size = (32, 32)
                    img = img.resize(new_size)
                self.matrix.draw_image_layout(
                    layout.holiday_image, 
                    img, 
                )
                
            # Gradiant
            self.matrix.draw_image_layout(layout.gradiant, black_gradiant)

            # Text 
            fg_rgb = _hex_to_rgb(theme.fg)
            self.matrix.draw_text_layout(layout.count_text, str(days_til), fillColor=fg_rgb)
            
            self.matrix.render()
            self.sleepEvent.wait(1)
           
            self.matrix.draw_text_layout(layout.until_text, "DAYS TIL", fillColor=fg_rgb)
            
            self.matrix.render()
            self.sleepEvent.wait(1)
            
            self.matrix.draw_text_layout(layout.holiday_name_text, name.upper(), fillColor=fg_rgb)

            self.matrix.render()
            self.sleepEvent.wait(7)

    # -------- Data building --------

    def _compute_upcoming(self) -> list[tuple[date, str]]:
        lib = self._upcoming_holidays_within(
            country=self.country_code,
            subdiv=self.subdiv,
            horizon_days=self.horizon_days,
            include_today=True,
        )  # list[(date, name)]

        # from CSV
        custom = []
        for dt, name, _meta in self.custom_rows:
            if 0 <= (dt - self.today).days <= self.horizon_days:
                custom.append((dt, name))

        merged = {(dt, name) for (dt, name) in lib} | {(dt, name) for (dt, name) in custom}
        return sorted(list(merged), key=lambda x: x[0])

    def _upcoming_holidays_within(
        self,
        country: str,
        subdiv: str | None = None,
        language: str | None = None,
        start: date | None = None,
        horizon_days: int = 90,
        include_today: bool = True,
    ) -> list[tuple[date, str]]:
        start = start or self.today
        years = {start.year, (start + timedelta(days=horizon_days)).year}
        
        # Not sure how to handle this better but I don't love this approach
        kwargs = {}
        if self.categories:   # will be False if [], "", or None
            kwargs["categories"] = []
            if "government".lower() in self.categories:
                kwargs["categories"].append(GOVERNMENT)
            if "unofficial".lower() in self.categories:
                kwargs["categories"].append(UNOFFICIAL)
            if "public".lower() in self.categories:
                kwargs["categories"].append(PUBLIC)

        hdays = country_holidays(
            country=country,
            subdiv=subdiv,
            years=sorted(years),
            language=language,
            **kwargs
        )

        results: list[tuple[date, str]] = []
        cursor = start

        if include_today and cursor in hdays:
            results.append((cursor, hdays[cursor]))
            cursor = cursor + timedelta(days=1)

        while True:
            nxt = hdays.get_closest_holiday(cursor)
            if not nxt:
                break
            nxt_dt, nxt_name = nxt
            if (nxt_dt - start).days <= horizon_days:
                results.append((nxt_dt, nxt_name))
                cursor = nxt_dt + timedelta(days=1)
            else:
                break

        return results

    # -------- Theme selection & assets --------

    def _get_csv_meta(self, dt: date, name: str) -> dict | None:
        norm = _normalize_name(name)
        for r_dt, r_name, meta in self.custom_rows:
            if r_dt == dt and _normalize_name(r_name) == norm:
                return meta
        return None

    def _pick_theme(self, name: str, csv_meta: dict | None) -> HolidayTheme:
        base = self.themes.get(_normalize_name(name), self.themes["default"])
        if not csv_meta:
            return base
        return HolidayTheme(
            fg=csv_meta.get("fg") or base.fg,
            bg=csv_meta.get("bg") or base.bg,
            image=csv_meta.get("image") or base.image,
        )

    def _open_image(self, path: str) -> Optional[Image.Image]:
        if path in self._image_cache:
            return self._image_cache[path]
        try:
            # Resolve path relative to board directory
            resolved_path = self._resolve_path(path)
            img = Image.open(resolved_path).convert("RGBA")
            self._image_cache[path] = img
            return img
        except Exception as e:
            debug.error(f"Failed to load image {path}: {e}")
            return None