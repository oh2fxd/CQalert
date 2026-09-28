"""Application configuration, constants, and WSJT-X config loaders.

Reads WSJT-X.ini for station callsign, grid, and UDP settings.
Defines all color schemes, tile dimensions, timeout values,
and the band/frequency lookup table.
"""

import configparser
import os
import re
from pathlib import Path
from typing import Optional

__all__ = [
    # Paths
    "WSJTX_DATA_DIR",
    "ALLTXT_PATH",
    "ADIF_PATH",
    "LOTW_PATH",
    "WSJTX_INI",
    "CTY_PATHS",
    "FLAG_DIRS",
    # Regex
    "GRID_RE",
    "CALL_RE",
    "ADIF_CALL_RE",
    "ADIF_FIELD_RE",
    # Tuning
    "APP_TITLE",
    "WINDOW_SECONDS",
    "MAX_STATIONS",
    "BOOTSTRAP_BYTES",
    "MQTT_HOST",
    "MQTT_PORT",
    "WSJTX_MAGIC",
    "WSJTX_SCHEMA",
    "WSJTX_PULSE_SECONDS",
    "UI_TICK_MS",
    "PRUNE_EVERY_SECONDS",
    # Colors
    "DEFAULT_BG",
    "CARD_NEW",
    "CARD_WORKED",
    "CARD_HEARDME",
    "CARD_TEXT",
    "MUTED",
    "ACCENT",
    "WARN",
    "ALERT",
    "OVERLAY_BG",
    # Layout
    "TILE_WIDTH",
    "TILE_HEIGHT",
    "TILE_GAP",
    "SCREEN_MARGIN",
    # Timing
    "SNOOZE_SECONDS",
    "STAR_TILE_SECONDS",
    "MIN_DISTANCE_ALERT_KM",
    "BAND_FILTERS",
    # Overrides
    "COUNTRY_OVERRIDES",
    # Loaders
    "load_station_config",
    "load_wsjtx_udp_config",
    "band_from_freq_mhz",
    "find_cty_path",
    "clean_country_name",
    "iso_to_flag",
]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
WSJTX_DATA_DIR = Path(os.environ.get("WSJTX_DIR", Path.home() / ".local/share/WSJT-X"))
ALLTXT_PATH = WSJTX_DATA_DIR / "ALL.TXT"
ADIF_PATH = WSJTX_DATA_DIR / "wsjtx_log.adi"
LOTW_PATH = WSJTX_DATA_DIR / "lotw-user-activity.csv"
WSJTX_INI = Path(os.environ.get("WSJTX_INI", Path.home() / ".config/WSJT-X.ini"))
CTY_PATHS = [
    WSJTX_DATA_DIR / "cty.dat",
    Path("/usr/share/wsjtx/cty.dat"),
    Path("/usr/share/hamradio-files/cty.dat"),
    Path("/usr/share/xdx/cty.dat"),
]
FLAG_DIRS = [
    Path("/usr/share/iso-flag-png"),
    Path("/usr/share/circle-flags-svg"),
    Path("/usr/share/lxpanel/images/xkb-flags"),
]

# ---------------------------------------------------------------------------
# Compiled regular expressions
# ---------------------------------------------------------------------------
GRID_RE = re.compile(r"^(?:[A-R]{2}\d{2})(?:[A-X]{2})?(?:\d{2})?$", re.IGNORECASE)
CALL_RE = re.compile(r"[A-Z0-9/]+")
ADIF_CALL_RE = re.compile(r"<call:\d+>([^<\s]+)", re.IGNORECASE)
ADIF_FIELD_RE = re.compile(r"<([a-z_]+):(\d+)(?::[^>]*)?>([^<]*)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
APP_TITLE = "CQAlert"
WINDOW_SECONDS = 5 * 60  # how long a regular tile stays visible
MAX_STATIONS = 80  # max tiles at once
BOOTSTRAP_BYTES = 700_000  # bytes read from end of ALL.TXT on startup
MQTT_HOST = "mqtt.pskreporter.info"
MQTT_PORT = 1883
WSJTX_MAGIC = 0xADBCCBDA
WSJTX_SCHEMA = 3
WSJTX_PULSE_SECONDS = 15  # interval between WSJT-X heartbeats
UI_TICK_MS = 1500  # ms between UI refresh ticks
PRUNE_EVERY_SECONDS = 10  # how often stale stations are pruned

# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------
DEFAULT_BG = "#0b1220"
CARD_NEW = "#173321"
CARD_WORKED = "#2b3143"
CARD_HEARDME = "#1d2940"
CARD_TEXT = "#eef4ff"
MUTED = "#9db0cb"
ACCENT = "#79e3a7"
WARN = "#ffd479"
ALERT = "#ff9f9f"
OVERLAY_BG = "#0f1726"

# ---------------------------------------------------------------------------
# Tile layout
# ---------------------------------------------------------------------------
TILE_WIDTH = 260
TILE_HEIGHT = 74
TILE_GAP = 8
SCREEN_MARGIN = 18

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
SNOOZE_SECONDS = 10 * 60
STAR_TILE_SECONDS = 15 * 60
MIN_DISTANCE_ALERT_KM = 0.0

BAND_FILTERS = {part.strip() for part in os.environ.get("FLAG_BANDS", "").split(",") if part.strip()}

# ---------------------------------------------------------------------------
# Country ISO overrides (pycountry fallbacks for non-standard entity names)
# ---------------------------------------------------------------------------
COUNTRY_OVERRIDES: dict[str, str] = {
    "Aland Islands": "AX",
    "Asiatic Russia": "RU",
    "Austral Islands": "PF",
    "Azores": "PT",
    "Balearic Islands": "ES",
    "Belarus": "BY",
    "Bosnia-Herzegovina": "BA",
    "Canary Islands": "ES",
    "Ceuta & Melilla": "ES",
    "Corsica": "FR",
    "Crete": "GR",
    "Czech Republic": "CZ",
    "Dem. Rep. of the Congo": "CD",
    "Dodecanese": "GR",
    "East Malaysia": "MY",
    "England": "GB",
    "European Russia": "RU",
    "Fed. Rep. of Germany": "DE",
    "France": "FR",
    "Guantanamo Bay": "CU",
    "Hawaii": "US",
    "Ireland": "IE",
    "Italy": "IT",
    "ITU HQ": "CH",
    "Kosovo": "XK",
    "Madeira Islands": "PT",
    "Monaco": "MC",
    "Mongolia": "MN",
    "Netherlands": "NL",
    "Northern Ireland": "GB",
    "Ogasawara": "JP",
    "Republic of Korea": "KR",
    "Sardinia": "IT",
    "Scotland": "GB",
    "Sicily": "IT",
    "Slovak Republic": "SK",
    "Slovenia": "SI",
    "South Shetland Islands": "AQ",
    "Sov Mil Order of Malta": "MT",
    "Spain": "ES",
    "Spratly Islands": "MY",
    "Svalbard": "SJ",
    "Switzerland": "CH",
    "Timor - Leste": "TL",
    "Trinidad & Tobago": "TT",
    "Turkey": "TR",
    "United Arab Emirates": "AE",
    "United Nations HQ": "US",
    "United States": "US",
    "United States Virgin Islands": "VI",
    "Vienna Intl Ctr": "AT",
    "Wales": "GB",
    "West Malaysia": "MY",
}


# ===================================================================
# Config loaders
# ===================================================================


def load_station_config() -> tuple[str, str]:
    """Read own callsign and Maidenhead grid from WSJT-X.ini."""
    cfg = configparser.ConfigParser()
    cfg.read(WSJTX_INI)
    call = cfg.get("Configuration", "MyCall", fallback="OH2FXD").strip().upper() or "OH2FXD"
    grid = cfg.get("Configuration", "MyGrid", fallback="KP39MS").strip().upper() or "KP39MS"
    return call, grid


def load_wsjtx_udp_config() -> tuple[str, int, bool]:
    """Read UDP listening address, port, and AcceptUDPRequests flag."""
    cfg = configparser.ConfigParser()
    cfg.read(WSJTX_INI)
    host = cfg.get("Configuration", "UDPServer", fallback="127.0.0.1").strip() or "127.0.0.1"
    port = cfg.getint("Configuration", "UDPServerPort", fallback=2237)
    accept_udp = cfg.getboolean("Configuration", "AcceptUDPRequests", fallback=False)
    return host, port, accept_udp


def band_from_freq_mhz(freq_mhz: Optional[float]) -> Optional[str]:
    """Map a frequency in MHz to the nearest amateur HF band name."""
    if freq_mhz is None:
        return None
    bands = [
        (1.8, 2.0, "160m"),
        (3.5, 4.0, "80m"),
        (5.0, 5.5, "60m"),
        (7.0, 7.3, "40m"),
        (10.1, 10.15, "30m"),
        (14.0, 14.35, "20m"),
        (18.068, 18.168, "17m"),
        (21.0, 21.45, "15m"),
        (24.89, 24.99, "12m"),
        (28.0, 29.7, "10m"),
        (50.0, 54.0, "6m"),
    ]
    for low, high, name in bands:
        if low <= freq_mhz <= high:
            return name
    return None


def find_cty_path() -> Optional[Path]:
    """Return the first existing cty.dat path, or None."""
    for path in CTY_PATHS:
        if path.exists():
            return path
    return None


def clean_country_name(name: str) -> str:
    """Normalize whitespace in a country entity name."""
    return " ".join(name.replace("&", " & ").split())


def iso_to_flag(iso_code: Optional[str]) -> str:
    """Return a 2-letter ISO code or '??' for display when flag image missing."""
    if not iso_code or len(iso_code) != 2:
        return "??"
    return iso_code.upper()
