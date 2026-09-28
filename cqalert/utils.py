"""Utility functions — geography, call sign parsing, file tailing, ADIF parsing.

Purely functional helpers with no application state.
"""

import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from cqalert.config import (
    CALL_RE,
    GRID_RE,
    ADIF_CALL_RE,
    ADIF_FIELD_RE,
    BOOTSTRAP_BYTES,
    band_from_freq_mhz,
)

__all__ = [
    "maidenhead_to_latlon",
    "great_circle_km",
    "bearing_deg",
    "compass_label",
    "normalize_call",
    "looks_like_call",
    "extract_cq_call",
    "parse_alltxt",
    "alltxt_line_ts",
    "tail_from_end",
    "bootstrap_lines",
    "parse_adif_calls",
    "parse_adif_awards",
]


# ===================================================================
# Geography helpers
# ===================================================================


def maidenhead_to_latlon(grid: str) -> tuple[float, float]:
    """Convert a Maidenhead locator to (latitude, longitude) in degrees."""
    g = grid.strip()
    if len(g) < 4:
        raise ValueError(f"Grid too short: {grid}")
    g_upper = g.upper()

    lon = (ord(g_upper[0]) - ord("A")) * 20 - 180
    lat = (ord(g_upper[1]) - ord("A")) * 10 - 90
    lon += int(g_upper[2]) * 2
    lat += int(g_upper[3])
    lon_size, lat_size = 2.0, 1.0

    if len(g) >= 6:
        lon += (ord(g[4].lower()) - ord("a")) * (2.0 / 24.0)
        lat += (ord(g[5].lower()) - ord("a")) * (1.0 / 24.0)
        lon_size, lat_size = (2.0 / 24.0), (1.0 / 24.0)

    if len(g) >= 8:
        lon += int(g[6]) * (lon_size / 10.0)
        lat += int(g[7]) * (lat_size / 10.0)

    return lat + lat_size / 2.0, lon + lon_size / 2.0


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine great-circle distance between two points in km."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 in degrees (0-360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass_label(deg: float) -> str:
    """Convert bearing degrees to a compass point (N, NE, E, ...)."""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int(((deg % 360) + 22.5) // 45) % 8]


# ===================================================================
# Call sign helpers
# ===================================================================


def normalize_call(call: str) -> str:
    """Extract the first valid call-sign pattern from a string, upper-cased."""
    match = CALL_RE.search(call.upper())
    return match.group(0) if match else ""


NON_CALL_TOKENS = {
    "CQ", "QRZ", "DX", "DE", "RR73", "73", "RRR",
    "POTA", "SOTA", "IOTA", "BOTA", "TEST", "QRP", "FD", "WW", "WPX",
    "NA", "SA", "EU", "AF", "AS", "OC", "JA", "VK", "UP", "DOWN",
}


def looks_like_call(token: str) -> bool:
    """Return True if *token* looks like an amateur radio callsign."""
    token = normalize_call(token)
    if not token or token in NON_CALL_TOKENS:
        return False
    if GRID_RE.match(token):
        return False
    has_digit = any(ch.isdigit() for ch in token)
    has_alpha = any(ch.isalpha() for ch in token)
    return has_digit and has_alpha and 3 <= len(token) <= 12


# ===================================================================
# ALL.TXT parsing
# ===================================================================


def parse_alltxt(
    line: str, my_call: str
) -> Optional[tuple[str, Optional[str], Optional[int], bool, Optional[float], Optional[str]]]:
    """Parse a single ALL.TXT line.

    Returns (call, grid, snr, is_cq, freq_mhz, band) or None if not a
    decodes line or no callsign can be extracted.
    """
    parts = line.strip().split(maxsplit=7)
    if len(parts) < 8 or parts[2] != "Rx":
        return None

    snr = _parse_snr(parts[4])
    freq_mhz = _parse_freq(parts[1])
    band = _band_from_freq(freq_mhz)

    message = parts[7].strip()
    if not message:
        return None

    tokens = message.split()
    grid = _extract_grid_from_tokens(tokens)
    is_cq = bool(tokens and tokens[0].upper() in {"CQ", "QRZ"})
    remote_call = _extract_remote_call(tokens, my_call, is_cq)

    if not remote_call:
        return None
    return remote_call, grid, snr, is_cq, freq_mhz, band


def _parse_snr(raw: str) -> Optional[int]:
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_freq(raw: str) -> Optional[float]:
    try:
        return float(raw)
    except ValueError:
        return None


def _band_from_freq(freq_mhz: Optional[float]) -> Optional[str]:
    """Map a frequency in MHz to the nearest amateur HF band name."""
    return band_from_freq_mhz(freq_mhz)


def _extract_grid_from_tokens(tokens: list[str]) -> Optional[str]:
    """Return the last Maidenhead grid found in token list, or None."""
    for token in reversed(tokens):
        up = token.upper()
        if GRID_RE.match(up):
            return up
    return None


def _extract_remote_call(tokens: list[str], my_call: str, is_cq: bool) -> Optional[str]:
    """Determine the remote callsign from a decoded message."""
    if is_cq:
        return _cq_call(tokens)
    return _noncq_call(tokens, my_call)


def _cq_call(tokens: list[str]) -> Optional[str]:
    """Extract callsign from a CQ/QRZ-style message (including directed CQs like CQ POTA, CQ NA, etc.)."""
    if not tokens or tokens[0].upper() not in {"CQ", "QRZ"}:
        return None
    end_idx = len(tokens)
    if end_idx > 2 and (GRID_RE.match(tokens[-1].upper()) or tokens[-1].upper() in {"73", "RR73", "RRR"}):
        end_idx -= 1
    # Search from right to left up to token index 1
    for idx in range(end_idx - 1, 0, -1):
        token = tokens[idx]
        if looks_like_call(token):
            return normalize_call(token)
    return None


extract_cq_call = _cq_call


def _noncq_call(tokens: list[str], my_call: str) -> Optional[str]:
    """Extract callsign from a non-CQ message (reply, report, etc.)."""
    calls = [normalize_call(token) for token in tokens if looks_like_call(token)]
    calls = [call for call in calls if call]
    if not calls:
        return None
    if my_call in calls:
        others = [call for call in calls if call != my_call]
        return others[0] if others else None
    return calls[0]


def alltxt_line_ts(line: str) -> Optional[float]:
    """Extract the Unix timestamp from the ALL.TXT date/time prefix."""
    parts = line.strip().split(maxsplit=1)
    if not parts:
        return None
    stamp = parts[0]
    try:
        dt = datetime.strptime(stamp, "%y%m%d_%H%M%S")
        return dt.timestamp()
    except Exception:
        return None


# ===================================================================
# File tailing
# ===================================================================


def tail_from_end(path: Path):
    """Yield lines from *path* as they are appended (follow mode).

    Seeks to the end and polls for new content every 250 ms. Handles file rotation/truncation.
    """
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        handle.seek(0, os.SEEK_END)
        buf = ""
        while True:
            try:
                curr_size = path.stat().st_size
                if curr_size < handle.tell():
                    handle.seek(0, os.SEEK_SET)
                    buf = ""
            except Exception:
                pass

            chunk = handle.read()
            if chunk:
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    yield line.rstrip("\r")
                continue
            time.sleep(0.25)


def bootstrap_lines(path: Path) -> list[str]:
    """Return the last ~2000 lines from *path* (reads from end)."""
    if not path.exists():
        return []
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - BOOTSTRAP_BYTES))
        chunk = handle.read().decode("utf-8", errors="ignore")
    lines = chunk.splitlines()
    if size > BOOTSTRAP_BYTES and len(lines) > 1:
        lines = lines[1:]
    return lines[-2000:]


# ===================================================================
# ADIF parsing
# ===================================================================


def parse_adif_calls(path: Path) -> set[str]:
    """Extract all unique callsigns from an ADIF log."""
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {normalize_call(match.group(1)) for match in ADIF_CALL_RE.finditer(text) if normalize_call(match.group(1))}


def parse_adif_awards(
    path: Path,
    dxcc: "DXCCResolver",  # noqa: F821 — forward ref resolved at runtime
) -> tuple[set[str], set[str], set[str], dict[str, set[str]], dict[str, set[str]]]:
    """Parse worked calls, countries, states, and per-band worked sets from ADIF.

    Returns (worked_calls, worked_countries, worked_states,
             worked_call_bands, worked_country_bands).
    """
    worked_calls: set[str] = set()
    worked_countries: set[str] = set()
    worked_states: set[str] = set()
    worked_call_bands: dict[str, set[str]] = {}
    worked_country_bands: dict[str, set[str]] = {}

    if not path.exists():
        return worked_calls, worked_countries, worked_states, worked_call_bands, worked_country_bands

    text = path.read_text(encoding="utf-8", errors="ignore")
    for record in text.split("<eor>"):
        fields = _parse_adif_record(record)
        call = normalize_call(fields.get("call", ""))
        if not call:
            continue
        worked_calls.add(call)

        country = dxcc.country_for_call(call)
        if country:
            worked_countries.add(country)

        band = fields.get("band", "").strip()
        if band:
            worked_call_bands.setdefault(call, set()).add(band)
            if country:
                worked_country_bands.setdefault(country, set()).add(band)

        state = fields.get("state", "").strip().upper()
        if state:
            worked_states.add(state)

    return worked_calls, worked_countries, worked_states, worked_call_bands, worked_country_bands


def _parse_adif_record(record: str) -> dict[str, str]:
    """Parse a single ADIF record (<eor> delimited) into a field dict."""
    fields: dict[str, str] = {}
    for match in ADIF_FIELD_RE.finditer(record):
        name = match.group(1).lower()
        length = int(match.group(2))
        value = match.group(3)[:length].strip()
        fields[name] = value
    return fields
