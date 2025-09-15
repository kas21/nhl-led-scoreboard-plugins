# Holiday Countdown Board

The **Holiday Countdown Board** displays upcoming holidays on an LED matrix with customizable colors and images.

It is powered by the [Python `holidays` library](https://github.com/vacanza/holidays) and supports both official holidays and custom user-defined holidays (like birthdays or anniversaries).

---

## Features

- Displays days until the next holiday within a configurable horizon.
- Supports country/subdivision selection via the `holidays` library.
- Ignore specific holidays you don’t want to show.
- Add **custom holidays** (recurring or fixed-date).
- Apply per-holiday **themes** (foreground color, background color, image).
- Default theme fallback ensures all holidays have consistent styling.

---  

### Config fields

- `holiday_countdown_country_code` → two-letter country code (e.g., `"US"`, `"CA"`, `"GB"`).
- `holiday_countdown_subdiv` → optional subdivision/state code (e.g., `"NY"`, `"CA"`).
- `holiday_countdown_ignored_holidays` → list of holiday names to ignore.
- `holiday_countdown_horizon_days` → how many days ahead to look for upcoming holidays.
- `holiday_countdown_themes_path` → path to a JSON file defining holiday themes.
- `holiday_countdown_custom_csv` → path to a CSV file defining custom holidays.


```toml

# Example snippet (replace with your actual config format)

"holiday_countdown": {

    "country_code": "US",

    "subdiv": "NY",

    "categories": ["GOVERNMENT", "UNOFFICIAL"],

    "horizon_days": 90,

    "ignored_holidays": [

        "Columbus Day",

        "Veterans Day"

    ],

    "themes_path": "src/data/holiday_themes.json",

    "custom_csv": "src/data/custom_holidays.csv"

}

```
  
---

## Theming

Holiday appearance is controlled by a `themes.json` file.
- Keys are holiday names (exact match, case-insensitive).
- Each entry can define `fg`, `bg`, and `image`.
- A `"default"` theme must exist as fallback.

### Example `themes.json`

```json

{
"default": {
    "fg": "#FFFFFF",
    "bg": "#000000",
    "image": "assets/holidays/default.png"
},

"Valentine's Day": {
    "fg": "#FFB7C5",
    "bg": "#A80030",
    "image": "assets/holidays/valentines.png"
},
"Halloween": {
    "fg": "#FFA500",
    "bg": "#000000",
    "image": "assets/holidays/halloween.png"
}
}

```

---

## Custom Holidays

You can add birthdays, anniversaries, or other non-official events via a `custom_holidays.csv` file.

### Example `custom_holidays.csv`

```csv

name,date,image,fg,bg
Ovi's Birthday,07-22,assets/holidays/birthday_ethan.png,#000000,#FFD166
Our Anniversary,11-15,assets/holidays/anniversary.png,#FFFFFF,#E63946

```

- `date` can be:
- `MM-DD` → repeats every year.
- `YYYY-MM-DD` → fixed one-time date.
- Optional `image`, `fg`, and `bg` override theme settings.
  