"""CQAlert application — the main GUI and event loop.

Orchestrates WSJT-X file tailing, MQTT listening, UDP protocol handling,
and tkinter overlay tile rendering.
"""

import json
import os
import queue
import socket
import struct
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import paho.mqtt.client as mqtt
from PIL import Image, ImageTk

from cqalert.config import (
    ADIF_PATH,
    ALLTXT_PATH,
    LOTW_PATH,
    FLAG_DIRS,
    APP_TITLE,
    DEFAULT_BG,
    CARD_NEW,
    CARD_WORKED,
    CARD_HEARDME,
    CARD_TEXT,
    MUTED,
    ACCENT,
    WARN,
    ALERT,
    OVERLAY_BG,
    TILE_WIDTH,
    TILE_HEIGHT,
    TILE_GAP,
    SCREEN_MARGIN,
    WINDOW_SECONDS,
    MAX_STATIONS,
    MQTT_HOST,
    MQTT_PORT,
    WSJTX_MAGIC,
    WSJTX_SCHEMA,
    WSJTX_PULSE_SECONDS,
    UI_TICK_MS,
    PRUNE_EVERY_SECONDS,
    SNOOZE_SECONDS,
    STAR_TILE_SECONDS,
    MIN_DISTANCE_ALERT_KM,
    BAND_FILTERS,
    load_station_config,
    load_wsjtx_udp_config,
    band_from_freq_mhz,
)
from cqalert.utils import (
    maidenhead_to_latlon,
    great_circle_km,
    bearing_deg,
    compass_label,
    normalize_call,
    looks_like_call,
    extract_cq_call,
    parse_alltxt,
    alltxt_line_ts,
    tail_from_end,
    bootstrap_lines,
    parse_adif_awards,
)
from cqalert.dxcc import DXCCResolver
from cqalert.protocol import (
    WSJTXDecode,
    WSJTXQsoLogged,
    QtStreamReader,
    build_heartbeat_payload,
    build_replay_payload,
    build_reply_payload,
    parse_status_payload,
    parse_qso_logged_payload,
)

__all__ = [
    "HeardStation",
    "OverlayTile",
    "CQAlertApp",
    "main",
]


# ===================================================================
# Domain models
# ===================================================================


@dataclass
class HeardStation:
    """A station spotted via ALL.TXT or PSK Reporter."""

    call: str
    grid: Optional[str]
    snr: Optional[int]
    ts: float
    is_cq: bool
    source: str = "heard"
    band: Optional[str] = None
    mode: Optional[str] = None
    freq_mhz: Optional[float] = None
    heard_count: int = 1
    lat: Optional[float] = None
    lon: Optional[float] = None
    distance_km: Optional[float] = None
    bearing_deg: Optional[float] = None

    def update_geo(self, my_lat: float, my_lon: float):
        """Precompute latitude, longitude, distance, and bearing from station grid."""
        if not self.grid:
            self.lat = None
            self.lon = None
            self.distance_km = None
            self.bearing_deg = None
            return
        try:
            self.lat, self.lon = maidenhead_to_latlon(self.grid)
            self.distance_km = great_circle_km(my_lat, my_lon, self.lat, self.lon)
            self.bearing_deg = bearing_deg(my_lat, my_lon, self.lat, self.lon)
        except Exception:
            self.lat = None
            self.lon = None
            self.distance_km = None
            self.bearing_deg = None


@dataclass
class OverlayTile:
    """A live tkinter overlay tile window."""

    key: str
    window: tk.Toplevel
    title_var: tk.StringVar
    line_var: tk.StringVar
    star_label: tk.Label
    age_bar: tk.Frame
    station: HeardStation


# ===================================================================
# Continent colour mapping
# ===================================================================

_CONTINENT_COLORS: dict[str, tuple[str, str]] = {
    "EU": ("#19304a", "#8ec5ff"),
    "AS": ("#3c2810", "#ffcc7a"),
    "NA": ("#153321", "#7fe6a5"),
    "SA": ("#3a1f12", "#ffb38a"),
    "AF": ("#3a3512", "#f3e37c"),
    "OC": ("#23173e", "#c5a3ff"),
    "AN": ("#2b2f38", "#d5dde8"),
}


# ===================================================================
# Main application class
# ===================================================================


class CQAlertApp:
    """Desktop overlay that shows fresh unworked CQ stations as alert tiles."""

    def __init__(self):
        # --- Station identity ---
        self.my_call, self.my_grid = load_station_config()
        self.my_lat, self.my_lon = maidenhead_to_latlon(self.my_grid)
        self.mqtt_topic = f"pskr/filter/v2/+/+/{self.my_call}/#"
        self.udp_host, self.udp_port, self.accept_udp = load_wsjtx_udp_config()

        # --- Data sources ---
        self.dxcc = DXCCResolver()
        self._load_worked_data()
        self.heard: dict[str, HeardStation] = {}
        self.heard_me: dict[str, HeardStation] = {}
        self.wsjtx_decodes: dict[str, WSJTXDecode] = {}
        self.wsjtx_lock = threading.Lock()
        self.heard_lock = threading.Lock()  # documents thread model

        # --- WSJT-X UDP state ---
        self.wsjtx_client_addr: Optional[tuple[str, int]] = None
        self.wsjtx_remote_id: Optional[str] = None
        self.wsjtx_schema = WSJTX_SCHEMA
        self.wsjtx_socket: Optional[socket.socket] = None
        self.wsjtx_app_id = f"{APP_TITLE}-{os.getpid()}"
        self.last_wsjtx_heartbeat = 0.0
        self.last_prune_check = 0.0
        self.current_band: Optional[str] = None

        # --- Event queue (thread-safe) ---
        self.events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.last_status = "Starting..."

        # --- UI state ---
        self.flag_cache: dict[tuple[str, int, int], object] = {}
        self.tiles: dict[str, OverlayTile] = {}
        self.snoozed_until: dict[str, float] = {}
        self.lotw_calls = self._load_lotw_calls()

        # --- tkinter ---
        self.root = tk.Tk()
        self.root.withdraw()
        self.heartbeat_var = tk.StringVar(master=self.root, value="♡ WSJT-X waiting")
        self.heartbeat_win = self._create_heartbeat_window()

        # --- Workers ---
        threading.Thread(target=self._tail_worker, daemon=True, name="tail").start()
        threading.Thread(target=self._mqtt_worker, daemon=True, name="mqtt").start()
        threading.Thread(target=self._wsjtx_udp_worker, daemon=True, name="udp").start()

        # --- UI ticks ---
        self.root.after(UI_TICK_MS, self._drain_events)
        self.root.after(250, self._animate_heartbeat)

    # ================================================================
    # Initialisation helpers
    # ================================================================

    def _load_worked_data(self):
        """Load worked-call/worked-country data from the ADIF log."""
        (
            self.worked_calls,
            self.worked_countries,
            self.worked_states,
            self.worked_call_bands,
            self.worked_country_bands,
        ) = parse_adif_awards(ADIF_PATH, self.dxcc)
        self.worked_mtime = ADIF_PATH.stat().st_mtime if ADIF_PATH.exists() else 0.0

    def _load_lotw_calls(self) -> set[str]:
        """Load LoTW-uploaded callsigns from the WSJT-X lotw CSV."""
        if not LOTW_PATH.exists():
            return set()
        calls: set[str] = set()
        try:
            with LOTW_PATH.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    call = normalize_call(line.split(",", 1)[0].strip())
                    if call:
                        calls.add(call)
        except Exception:
            return set()
        return calls

    # ================================================================
    # Heartbeat overlay window
    # ================================================================

    def _create_heartbeat_window(self) -> tk.Toplevel:
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=OVERLAY_BG)
        frame = tk.Frame(
            win,
            bg=OVERLAY_BG,
            highlightbackground="#3c4a66",
            highlightthickness=1,
            padx=10,
            pady=6,
        )
        frame.pack(fill="both", expand=True)
        self.heartbeat_label = tk.Label(
            frame,
            textvariable=self.heartbeat_var,
            bg=OVERLAY_BG,
            fg=ALERT,
            font=("DejaVu Sans", 12, "bold"),
            anchor="w",
        )
        self.heartbeat_label.pack()
        return win

    def _position_heartbeat_window(self):
        screen_w = self.root.winfo_screenwidth()
        x = screen_w - 220 - SCREEN_MARGIN
        y = SCREEN_MARGIN
        self.heartbeat_win.geometry(f"220x34+{x}+{y}")

    # ================================================================
    # Heartbeat animation
    # ================================================================

    def _animate_heartbeat(self):
        age = time.time() - self.last_wsjtx_heartbeat if self.last_wsjtx_heartbeat else 9999
        if age < 20.0:
            beat_phase = int(time.time() * 2) % 2
            heart = "♥" if beat_phase == 0 else "♡"
            color = "#ff6b6b" if beat_phase == 0 else "#ff9e9e"
            band_info = f" [{self.current_band}]" if self.current_band else ""
            text = f"{heart} WSJT-X connected{band_info}"
            font = ("DejaVu Sans", 12, "bold")
        elif age < WSJTX_PULSE_SECONDS * 3:
            heart = "♡"
            color = WARN
            text = f"{heart} WSJT-X quiet {int(age)}s"
            font = ("DejaVu Sans", 12, "bold")
        else:
            heart = "♡"
            color = ALERT
            text = f"{heart} WSJT-X waiting"
            font = ("DejaVu Sans", 12, "bold")
        self.heartbeat_var.set(text)
        self.heartbeat_label.configure(fg=color, font=font)
        self.root.after(250, self._animate_heartbeat)

    # ================================================================
    # Flash notice (temporary popup)
    # ================================================================

    def _flash_notice(self, text: str, bg: str = "#173321"):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        frame = tk.Frame(
            win,
            bg=bg,
            highlightbackground="#ffffff",
            highlightthickness=1,
            padx=10,
            pady=6,
        )
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text=text,
            bg=bg,
            fg="#ffffff",
            font=("DejaVu Sans", 10, "bold"),
        ).pack()
        screen_w = self.root.winfo_screenwidth()
        x = screen_w - 220 - SCREEN_MARGIN
        y = SCREEN_MARGIN + 42
        win.geometry(f"220x34+{x}+{y}")
        self.root.after(1800, win.destroy)

    # ================================================================
    # Station helpers
    # ================================================================

    def _visible_stations(self) -> list[HeardStation]:
        now = time.time()
        fresh = [
            station
            for station in self.heard.values()
            if self._station_is_alive(station, now)
            and station.call not in self.worked_calls
            and self._station_min_distance_ok(station)
            and self._passes_band_filter(station)
            and self._not_snoozed(station, now)
        ]
        fresh.sort(key=self._station_sort_key)
        return fresh[:MAX_STATIONS]

    def _station_is_alive(self, station: HeardStation, now: float) -> bool:
        _flag, country, _iso = self._station_meta(station)
        ttl = STAR_TILE_SECONDS if self._station_star(station, country) else WINDOW_SECONDS
        return now - station.ts <= ttl

    def _station_min_distance_ok(self, station: HeardStation) -> bool:
        return self._station_distance_km(station) >= MIN_DISTANCE_ALERT_KM

    def _passes_band_filter(self, station: HeardStation) -> bool:
        if not BAND_FILTERS:
            return True
        return (station.band or "") in BAND_FILTERS

    def _not_snoozed(self, station: HeardStation, now: float) -> bool:
        return self.snoozed_until.get(self._tile_key(station), 0) <= now

    def _station_sort_key(self, station: HeardStation):
        _flag, country, _iso = self._station_meta(station)
        return (
            not self._station_star(station, country),
            -self._station_distance_km(station),
            -station.ts,
        )

    def _station_meta(self, station: HeardStation) -> tuple[str, str, str]:
        country = self.dxcc.country_for_call(station.call)
        iso_code = self.dxcc.iso_for_country(country)
        flag = iso_code.upper() if iso_code else "??"
        return flag, country or "Unknown DXCC", iso_code or ""

    def _station_distance_km(self, station: HeardStation) -> float:
        if station.distance_km is not None:
            return station.distance_km
        if not station.grid:
            return -1.0
        station.update_geo(self.my_lat, self.my_lon)
        return station.distance_km if station.distance_km is not None else -1.0

    def _station_bearing(self, station: HeardStation) -> Optional[float]:
        if station.bearing_deg is not None:
            return station.bearing_deg
        if not station.grid:
            return None
        station.update_geo(self.my_lat, self.my_lon)
        return station.bearing_deg

    def _station_state(self, station: HeardStation, country: str) -> Optional[str]:
        # Reserved for future state-tracking data source.
        _ = station
        _ = country
        return None

    def _station_star(self, station: HeardStation, country: str) -> bool:
        """Return True if the station is a 'wanted' target."""
        if country and country not in self.worked_countries:
            return True
        state = self._station_state(station, country)
        if state and state not in self.worked_states:
            return True
        if station.band and country and station.band not in self.worked_country_bands.get(country, set()):
            return True
        return False

    def _wanted_reason(self, station: HeardStation, country: str) -> Optional[str]:
        if country and country not in self.worked_countries:
            return "New DXCC"
        state = self._station_state(station, country)
        if state and state not in self.worked_states:
            return "New State"
        if station.band and country and station.band not in self.worked_country_bands.get(country, set()):
            return "New Band-DXCC"
        return None

    def _continent_for_country(self, country: str) -> str:
        return self.dxcc.continent_for_country(country)

    def _continent_colors(self, continent: str) -> tuple[str, str]:
        return _CONTINENT_COLORS.get(continent, (CARD_NEW, ACCENT))

    def _get_flag_image(self, iso_code: str, width: int, height: int):
        if not iso_code:
            return None
        key = (iso_code.lower(), width, height)
        if key in self.flag_cache:
            return self.flag_cache[key]

        image = self._load_flag_file(iso_code.lower(), width, height)
        if image is None:
            self.flag_cache[key] = None
            return None
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        rendered = ImageTk.PhotoImage(image)
        self.flag_cache[key] = rendered
        return rendered

    def _load_flag_file(self, iso_lower: str, width: int, height: int):
        """Try to load a flag image from local filesystem (PNG or SVG)."""
        for base in FLAG_DIRS:
            png_path = base / f"{iso_lower}.png"
            svg_path = base / f"{iso_lower}.svg"
            if png_path.exists():
                return Image.open(png_path).convert("RGBA")
            if svg_path.exists():
                try:
                    import cairosvg

                    png_bytes = cairosvg.svg2png(
                        url=str(svg_path),
                        output_width=width * 2,
                        output_height=height * 2,
                    )
                    return Image.open(BytesIO(png_bytes)).convert("RGBA")
                except Exception:
                    continue
        return None

    def _station_distance(self, station: HeardStation) -> str:
        if not station.grid:
            return "distance n/a"
        try:
            lat, lon = maidenhead_to_latlon(station.grid)
            return f"{great_circle_km(self.my_lat, self.my_lon, lat, lon):.0f} km"
        except Exception:
            return "distance n/a"

    def _heard_age(self, station: HeardStation) -> str:
        age = max(0, int(time.time() - station.ts))
        if age < 60:
            return f"{age}s ago"
        minutes, seconds = divmod(age, 60)
        return f"{minutes}m {seconds:02d}s ago"

    def _tile_key(self, station: HeardStation) -> str:
        return f"{station.source}:{station.call}"

    # ================================================================
    # Tile lifecycle
    # ================================================================

    def _destroy_tile(self, key: str):
        tile = self.tiles.pop(key, None)
        if tile:
            try:
                tile.window.destroy()
            except Exception:
                pass

    def _dismiss_tile(self, key: str):
        """Dismiss a tile without working or arming the station in WSJT-X."""
        self._destroy_tile(key)
        return "break"

    def _tile_click_work(self, key: str):
        tile = self.tiles.get(key)
        if not tile:
            return "break"
        station = tile.station
        self._destroy_tile(key)
        self._work_station(station)
        return "break"

    def _tile_snooze(self, key: str):
        self.snoozed_until[key] = time.time() + SNOOZE_SECONDS
        self._destroy_tile(key)
        return "break"

    def _bind_click_recursive(self, widget: tk.Misc, key: str):
        if getattr(widget, "_has_custom_click", False):
            return
        widget.bind("<Button-1>", lambda _e, k=key: self._tile_click_work(k))
        widget.bind("<Button-3>", lambda _e, k=key: self._tile_snooze(k))
        for child in widget.winfo_children():
            self._bind_click_recursive(child, key)

    def _create_tile(
        self,
        key: str,
        station: HeardStation,
        country: str,
        iso_code: str,
        distance: str,
        bg: str,
        border: str,
        starred: bool,
    ):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=DEFAULT_BG)

        outer = tk.Frame(
            win,
            bg=bg,
            highlightbackground=border,
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        outer.pack(fill="both", expand=True)

        # --- Top row: call + close + flag + star ---
        top = tk.Frame(outer, bg=bg)
        top.pack(fill="x")

        title_var = tk.StringVar(master=self.root, value=station.call)
        line_var = tk.StringVar(master=self.root, value="")

        tk.Label(
            top,
            textvariable=title_var,
            bg=bg,
            fg=CARD_TEXT,
            font=("DejaVu Sans Mono", 12, "bold"),
            anchor="w",
        ).pack(side="left")

        right = tk.Frame(top, bg=bg)
        right.pack(side="right")

        star_label = tk.Label(
            right,
            text="★",
            bg=bg,
            fg="#ffd75e",
            font=("DejaVu Sans", 12, "bold"),
        )
        if starred:
            star_label.pack(side="right", padx=(0, 6))

        close_btn = tk.Label(
            right,
            text="×",
            bg=bg,
            fg="#ffb0b0",
            font=("DejaVu Sans", 12, "bold"),
            cursor="hand2",
        )
        close_btn._has_custom_click = True  # type: ignore[attr-defined]
        close_btn.pack(side="right", padx=(6, 0))
        close_btn.bind("<Button-1>", lambda _e, k=key: self._dismiss_tile(k))

        flag_img = self._get_flag_image(iso_code, 22, 14)
        if flag_img is not None:
            flag_label = tk.Label(right, image=flag_img, bg=bg, bd=0)
            flag_label.image = flag_img
            flag_label.pack(side="right", padx=(0, 4))
        else:
            tk.Label(
                right,
                text=iso_code or "??",
                bg=bg,
                fg=CARD_TEXT,
                font=("DejaVu Sans", 9, "bold"),
            ).pack(side="right", padx=(0, 4))

        # --- Info line ---
        tk.Label(
            outer,
            textvariable=line_var,
            bg=bg,
            fg=MUTED,
            font=("DejaVu Sans", 9),
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        # --- Age bar ---
        age_track = tk.Frame(outer, bg="#243047", height=3)
        age_track.pack(fill="x", pady=(5, 0))
        age_bar = tk.Frame(
            age_track,
            bg="#79e3a7",
            height=3,
            width=TILE_WIDTH - 20,
        )
        age_bar.place(x=0, y=0)

        tile = OverlayTile(
            key=key,
            window=win,
            title_var=title_var,
            line_var=line_var,
            star_label=star_label,
            age_bar=age_bar,
            station=station,
        )
        self.tiles[key] = tile

        win.bind("<Button-1>", lambda _e, k=key: self._tile_click_work(k))
        win.bind("<Button-3>", lambda _e, k=key: self._tile_snooze(k))
        self._bind_click_recursive(outer, key)
        self._update_tile(tile, station, country, distance, starred)

    def _update_tile(
        self,
        tile: OverlayTile,
        station: HeardStation,
        country: str,
        distance: str,
        starred: bool,
    ):
        tile.station = station
        tile.title_var.set(station.call)

        bearing = self._station_bearing(station)
        bearing_text = f"{int(round(bearing)):03d}° {compass_label(bearing)}" if bearing is not None else ""
        continent = self._continent_for_country(country)
        reason = self._wanted_reason(station, country)
        lotw = " LoTW" if station.call in self.lotw_calls else ""
        band = station.band or "?"
        age_text = self._heard_age(station)
        source_text = "CQ" if station.is_cq else ("heard me" if station.source == "heardme" else "heard")

        extra_parts = [
            band,
            continent,
            reason,
            f"SNR {station.snr}" if station.snr is not None else "",
            age_text,
            lotw.strip(),
        ]
        extras = "  ".join(p for p in extra_parts if p)
        second = f"{distance}  {bearing_text}  {country}".strip()
        tile.line_var.set(f"{source_text}  {extras}\n{second}")

        # Star visibility
        if starred and not tile.star_label.winfo_manager():
            tile.star_label.pack(side="right", padx=(0, 6))
        elif not starred and tile.star_label.winfo_manager():
            tile.star_label.pack_forget()

        # Age bar width
        ttl = STAR_TILE_SECONDS if starred else WINDOW_SECONDS
        age = max(0.0, time.time() - station.ts)
        frac = max(0.05, 1.0 - min(1.0, age / ttl))
        width = max(10, int((TILE_WIDTH - 20) * frac))
        tile.age_bar.configure(width=width, bg="#ffd75e" if starred else "#79e3a7")

    def _layout_tiles(self):
        self._position_heartbeat_window()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        start_x = screen_w - TILE_WIDTH - SCREEN_MARGIN
        start_y = SCREEN_MARGIN + 34 + TILE_GAP
        usable_h = max(TILE_HEIGHT, screen_h - start_y - SCREEN_MARGIN)
        rows_per_col = max(1, usable_h // (TILE_HEIGHT + TILE_GAP))
        ordered = sorted(self.tiles.values(), key=lambda t: self._station_sort_key(t.station))

        for idx, tile in enumerate(ordered):
            col = idx // rows_per_col
            row = idx % rows_per_col
            x = start_x - col * (TILE_WIDTH + TILE_GAP)
            y = start_y + row * (TILE_HEIGHT + TILE_GAP)
            tile.window.geometry(f"{TILE_WIDTH}x{TILE_HEIGHT}+{x}+{y}")

    def _render_cards(self):
        stations = self._visible_stations()
        wanted: set[str] = set()

        for station in stations:
            is_worked = station.call in self.worked_calls
            _flag, country, iso_code = self._station_meta(station)
            distance = self._station_distance(station)
            starred = self._station_star(station, country)
            continent = self._continent_for_country(country)

            if station.source == "heardme":
                bg = CARD_HEARDME
                border = "#81b7ff"
            else:
                base_bg, base_border = self._continent_colors(continent)
                if starred:
                    bg = base_bg
                elif is_worked:
                    bg = CARD_WORKED
                else:
                    bg = base_bg
                border = "#ffd75e" if starred else base_border

            key = self._tile_key(station)
            wanted.add(key)
            tile = self.tiles.get(key)

            if tile is None:
                self._create_tile(key, station, country, iso_code, distance, bg, border, starred)
                if starred:
                    try:
                        self.root.bell()
                    except Exception:
                        pass
            else:
                self._update_tile(tile, station, country, distance, starred)

        # Remove stale tiles
        for key in list(self.tiles):
            if key not in wanted:
                self._destroy_tile(key)

        self._layout_tiles()

    # ================================================================
    # Working a station (click action)
    # ================================================================

    def _work_station(self, station: HeardStation):
        clip_text = station.call if not station.grid else f"{station.call} {station.grid}"
        self.root.clipboard_clear()
        self.root.clipboard_append(clip_text)
        self.root.update_idletasks()

        focused = self._focus_wsjtx()

        if self.accept_udp and station.source == "heard":
            sent, reason = self._send_reply_for_station(station.call)
            if sent:
                self._flash_notice(f"Armed {station.call}", bg="#1d6b45")
                self.last_status = (
                    f"{clip_text} copied. WSJT-X {'focused' if focused else 'not focused'}, and a real Reply was sent."
                )
            else:
                self._flash_notice(f"Not armed: {station.call}", bg="#7a3d24")
                self.last_status = (
                    f"{clip_text} copied. WSJT-X {'focused' if focused else 'not focused'}. Reply not sent: {reason}"
                )
        elif self.accept_udp and station.source == "heardme":
            self._flash_notice(f"Copied {station.call}", bg="#3b4a66")
            self.last_status = (
                f"{clip_text} copied. WSJT-X {'focused' if focused else 'not focused'}. "
                "Remote PSK Reporter spots cannot be armed directly because they are not local CQ decodes."
            )
        else:
            self._flash_notice(f"Copied {station.call}", bg="#3b4a66")
            self.last_status = (
                f"{clip_text} copied. WSJT-X {'focused' if focused else 'not focused'}. "
                "Direct arming is off because WSJT-X has Accept UDP requests disabled."
            )

    def _focus_wsjtx(self) -> bool:
        """Try to bring the WSJT-X window to the foreground using wmctrl."""
        try:
            result = subprocess.run(
                ["wmctrl", "-a", "WSJT-X"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except Exception:
            return False

    # ================================================================
    # ADIF reload
    # ================================================================

    def _reload_worked_if_needed(self) -> bool:
        if not ADIF_PATH.exists():
            return False
        mtime = ADIF_PATH.stat().st_mtime
        if mtime <= self.worked_mtime:
            return False
        (
            self.worked_calls,
            self.worked_countries,
            self.worked_states,
            self.worked_call_bands,
            self.worked_country_bands,
        ) = parse_adif_awards(ADIF_PATH, self.dxcc)
        self.worked_mtime = mtime
        return True

    # ================================================================
    # Event ingestion
    # ================================================================

    def _ingest_line(self, line: str):
        parsed = parse_alltxt(line, self.my_call)
        if not parsed:
            return
        call, grid, snr, is_cq, freq_mhz, band = parsed
        if not is_cq or not grid:
            return
        now = time.time()
        station = self.heard.get(call)
        if station:
            if grid and grid != station.grid:
                station.grid = grid
                station.update_geo(self.my_lat, self.my_lon)
            station.snr = snr
            station.ts = now
            station.is_cq = station.is_cq or is_cq
            station.freq_mhz = freq_mhz if freq_mhz is not None else station.freq_mhz
            station.band = band or station.band
            station.heard_count += 1
        else:
            s = HeardStation(
                call=call,
                grid=grid,
                snr=snr,
                ts=now,
                is_cq=is_cq,
                freq_mhz=freq_mhz,
                band=band,
            )
            s.update_geo(self.my_lat, self.my_lon)
            self.heard[call] = s

    def _ingest_decode(self, decode: WSJTXDecode):
        if not decode.call:
            return
        with self.wsjtx_lock:
            self.wsjtx_decodes[decode.call] = decode

    def _clear_decodes(self):
        """Prune decodes older than WINDOW_SECONDS rather than wiping everything immediately."""
        cutoff = time.time() - WINDOW_SECONDS
        with self.wsjtx_lock:
            stale = [k for k, v in self.wsjtx_decodes.items() if v.ts < cutoff]
            for k in stale:
                self.wsjtx_decodes.pop(k, None)

    def _ingest_heard_me(self, item: dict):
        call = normalize_call(str(item.get("receiver", "")))
        if not call:
            return
        station = self.heard_me.get(call)
        ts = float(item.get("ts", time.time()))
        grid = item.get("rgrid")
        snr = item.get("snr")
        band = item.get("band")
        mode = item.get("mode")

        if station:
            if grid and grid != station.grid:
                station.grid = grid
                station.update_geo(self.my_lat, self.my_lon)
            station.snr = snr if snr is not None else station.snr
            station.band = band or station.band
            station.mode = mode or station.mode
            station.ts = ts
            station.heard_count += 1
        else:
            s = HeardStation(
                call=call,
                grid=grid,
                snr=snr,
                ts=ts,
                is_cq=False,
                source="heardme",
                band=band,
                mode=mode,
            )
            s.update_geo(self.my_lat, self.my_lon)
            self.heard_me[call] = s

    def _ingest_qso_logged(self, qso: WSJTXQsoLogged):
        """Immediately record a newly logged QSO from WSJT-X and dismiss its tile."""
        call = normalize_call(qso.dx_call)
        if not call:
            return
        self.worked_calls.add(call)
        country = self.dxcc.country_for_call(call)
        if country:
            self.worked_countries.add(country)
            band = band_from_freq_mhz(qso.dial_freq_hz / 1e6)
            if band:
                self.worked_call_bands.setdefault(call, set()).add(band)
                self.worked_country_bands.setdefault(country, set()).add(band)
        # Dismiss any active tiles for this call
        for k in list(self.tiles):
            if k.endswith(f":{call}"):
                self._destroy_tile(k)
        self._flash_notice(f"Logged {call}", bg="#194d33")

    def _prune_old(self) -> bool:
        cutoff = time.time() - WINDOW_SECONDS
        changed = False
        for d in (self.heard, self.heard_me):
            stale = [k for k, v in d.items() if v.ts < cutoff]
            for k in stale:
                d.pop(k, None)
                changed = True
        return changed

    # ================================================================
    # Background workers
    # ================================================================

    def _set_status(self, text: str):
        self.last_status = text

    def _tail_worker(self):
        """Watch ALL.TXT for new decodes."""
        if not ALLTXT_PATH.exists():
            self.events.put(("status", f"Missing {ALLTXT_PATH}"))
            return

        cutoff = time.time() - WINDOW_SECONDS
        for line in bootstrap_lines(ALLTXT_PATH):
            ts = alltxt_line_ts(line)
            if ts is not None and ts < cutoff:
                continue
            self.events.put(("line", line))
        self.events.put(("status", f"Watching {ALLTXT_PATH}"))

        try:
            for line in tail_from_end(ALLTXT_PATH):
                self.events.put(("line", line))
        except Exception as exc:
            self.events.put(("status", f"Tail stopped: {exc}"))

    def _mqtt_worker(self):
        """Listen to PSK Reporter MQTT for 'heard me' spots."""
        client = mqtt.Client()
        client.on_connect = self._mqtt_on_connect
        client.on_message = self._mqtt_on_message
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            self.events.put(("status", f"PSK Reporter unavailable: {exc}"))

    def _mqtt_on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        if int(reason_code) == 0:
            client.subscribe(self.mqtt_topic)
            self.events.put(("status", f"Watching {ALLTXT_PATH} and PSK Reporter {self.mqtt_topic}"))
        else:
            self.events.put(("status", f"PSK Reporter connect failed: {reason_code}"))

    def _mqtt_on_message(self, _client, _userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="ignore"))
            sender = str(payload.get("sc", "")).upper()
            if sender != self.my_call:
                return
            item = self._parse_psk_reporter_payload(payload)
            if item:
                self.events.put(("heardme", item))
        except Exception:
            return

    def _parse_psk_reporter_payload(self, payload: dict) -> Optional[dict]:
        """Convert a PSK Reporter JSON message to a standardised dict."""
        ts = payload.get("t", time.time())
        try:
            ts = float(ts)
            if ts < 1_000_000_000:
                ts = time.time()
        except Exception:
            ts = time.time()

        snr_raw = payload.get("rp")
        try:
            snr = int(snr_raw) if snr_raw is not None else None
        except (ValueError, TypeError):
            snr = None

        return {
            "ts": ts,
            "receiver": str(payload.get("rc", "")).upper(),
            "rgrid": str(payload.get("rl", "")).upper() or None,
            "snr": snr,
            "band": str(payload.get("b", "")).strip() or None,
            "mode": str(payload.get("md", "")).strip() or None,
        }

    def _wsjtx_udp_worker(self):
        """Listen for WSJT-X UDP heartbeats, decodes, status, and logged QSOs."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            try:
                sock.bind((self.udp_host, self.udp_port))
            except OSError:
                sock.bind(("", self.udp_port))
            sock.settimeout(1.0)
            self.wsjtx_socket = sock
            self.events.put(("status", f"WSJT-X UDP listening on {self.udp_host}:{self.udp_port}"))
        except Exception as exc:
            self.events.put(("status", f"WSJT-X UDP unavailable: {exc}"))
            return

        last_heartbeat = 0.0
        while True:
            now = time.time()
            if now - last_heartbeat >= WSJTX_PULSE_SECONDS:
                self._send_heartbeat()
                last_heartbeat = now
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception as exc:
                self.events.put(("status", f"WSJT-X UDP stopped: {exc}"))
                return
            self._handle_wsjtx_packet(data, addr)

    # ================================================================
    # WSJT-X UDP protocol handling
    # ================================================================

    def _handle_wsjtx_packet(self, data: bytes, addr: tuple[str, int]):
        try:
            stream = QtStreamReader(data)
            magic = stream.read_u32()
            if magic != WSJTX_MAGIC:
                return
            schema = stream.read_u32()
            msg_type = stream.read_u32()
            self.wsjtx_schema = min(WSJTX_SCHEMA, schema or WSJTX_SCHEMA)

            if msg_type == 0:
                self._handle_wsjtx_heartbeat(stream, addr)
            elif msg_type == 1:
                self._handle_wsjtx_status(stream, addr)
            elif msg_type == 2:
                self._handle_wsjtx_decode(stream, addr)
            elif msg_type == 3:
                self._clear_decodes()
            elif msg_type == 5:
                self._handle_wsjtx_qso_logged(stream)
            elif msg_type == 6:
                self._handle_wsjtx_clear(addr)
        except Exception:
            return

    def _handle_wsjtx_heartbeat(self, stream: QtStreamReader, addr: tuple[str, int]):
        wsjtx_id = stream.read_utf8()
        _max_schema = stream.read_u32() if stream.remaining() >= 4 else self.wsjtx_schema
        _version = stream.read_utf8() if stream.remaining() else ""
        _revision = stream.read_utf8() if stream.remaining() else ""
        self.last_wsjtx_heartbeat = time.time()
        self.wsjtx_remote_id = wsjtx_id
        self.wsjtx_client_addr = addr
        self._send_heartbeat()
        self._send_replay()
        self.events.put(("status", f"WSJT-X connected from {addr[0]}:{addr[1]}"))

    def _handle_wsjtx_status(self, stream: QtStreamReader, addr: tuple[str, int]):
        status = parse_status_payload(stream)
        self.last_wsjtx_heartbeat = time.time()
        self.wsjtx_client_addr = addr
        if status:
            self.wsjtx_remote_id = status.wsjtx_id
            if status.dial_freq_hz > 0:
                self.events.put(("band", band_from_freq_mhz(status.dial_freq_hz / 1e6)))

    def _handle_wsjtx_qso_logged(self, stream: QtStreamReader):
        qso = parse_qso_logged_payload(stream)
        if qso:
            self.events.put(("qso_logged", qso))

    def _handle_wsjtx_decode(self, stream: QtStreamReader, addr: tuple[str, int]):
        decode = self._parse_decode(stream)
        self.last_wsjtx_heartbeat = time.time()
        self.wsjtx_remote_id = decode.wsjtx_id
        self.wsjtx_client_addr = addr
        if decode.is_cq:
            self.events.put(("decode", decode))

    def _handle_wsjtx_clear(self, addr: tuple[str, int]):
        self.wsjtx_client_addr = None
        self.wsjtx_remote_id = None
        self._clear_decodes()

    def _parse_decode(self, stream: QtStreamReader) -> WSJTXDecode:
        wsjtx_id = stream.read_utf8()
        is_new = stream.read_bool()
        timestamp_ms = stream.read_qtime_ms()
        snr = stream.read_i32()
        delta_time = stream.read_double()
        delta_freq = stream.read_u32()
        mode = stream.read_utf8()
        message = stream.read_utf8()
        low_conf = stream.read_bool()
        _off_air = stream.read_bool() if stream.remaining() else False
        call, is_cq = self._extract_decode_target(message)
        return WSJTXDecode(
            wsjtx_id=wsjtx_id,
            timestamp_ms=timestamp_ms,
            snr=snr,
            delta_time=delta_time,
            delta_freq=delta_freq,
            mode=mode,
            message=message,
            low_conf=low_conf,
            is_new=is_new,
            call=call,
            is_cq=is_cq,
            ts=time.time(),
        )

    def _extract_decode_target(self, message: str) -> tuple[str, bool]:
        tokens = message.upper().split()
        if not tokens:
            return "", False
        is_cq = bool(tokens[0] in {"CQ", "QRZ"})
        if is_cq:
            call = extract_cq_call(tokens)
            return (call or "", True)
        calls = [normalize_call(token) for token in tokens if looks_like_call(token)]
        calls = [c for c in calls if c]
        return (calls[0], False) if calls else ("", False)

    # ================================================================
    # WSJT-X UDP message sending
    # ================================================================

    def _send_udp_message(self, msg_type: int, payload: bytes) -> bool:
        if not self.wsjtx_socket or not self.wsjtx_client_addr:
            return False
        packet = struct.pack(">III", WSJTX_MAGIC, self.wsjtx_schema, msg_type) + payload
        try:
            self.wsjtx_socket.sendto(packet, self.wsjtx_client_addr)
            return True
        except Exception:
            return False

    def _send_heartbeat(self):
        payload = build_heartbeat_payload(self.wsjtx_app_id, APP_TITLE)
        self._send_udp_message(0, payload)

    def _send_replay(self):
        payload = build_replay_payload(self.wsjtx_app_id)
        self._send_udp_message(7, payload)

    def _send_reply_for_station(self, call: str) -> tuple[bool, str]:
        with self.wsjtx_lock:
            decode = self.wsjtx_decodes.get(call)
        if not decode:
            return False, "no matching CQ/QRZ decode cached from WSJT-X yet"
        if not self.wsjtx_client_addr:
            return False, "WSJT-X UDP client not connected"
        if not self.wsjtx_remote_id:
            return False, "WSJT-X station id not known yet"

        payload = build_reply_payload(
            remote_id=self.wsjtx_remote_id,
            timestamp_ms=decode.timestamp_ms,
            snr=decode.snr,
            delta_time=decode.delta_time,
            delta_freq=decode.delta_freq,
            mode=decode.mode,
            message=decode.message,
            low_conf=decode.low_conf,
        )
        if self._send_udp_message(4, payload):
            return True, ""
        return False, "UDP send failed"

    # ================================================================
    # Event loop
    # ================================================================

    def _drain_events(self):
        """Process queued events from background workers on the main thread."""
        updated = self._process_event_queue()

        if self._reload_worked_if_needed():
            updated = True

        if self._check_prune():
            updated = True

        if updated:
            self._render_cards()
        else:
            self._refresh_active_tiles()

        self.root.after(UI_TICK_MS, self._drain_events)

    def _refresh_active_tiles(self):
        """Update age text and age bars on active tiles each tick even when no new stations arrived."""
        for tile in self.tiles.values():
            _flag, country, _iso = self._station_meta(tile.station)
            starred = self._station_star(tile.station, country)
            distance = self._station_distance(tile.station)
            self._update_tile(tile, tile.station, country, distance, starred)

    def _process_event_queue(self) -> bool:
        """Drain all pending events from the queue.  Returns True if anything changed."""
        updated = False
        while True:
            try:
                event_type, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if self._dispatch_event(event_type, payload):
                updated = True
        return updated

    def _dispatch_event(self, event_type: str, payload: object) -> bool:
        """Handle a single event.  Returns True if the UI may need to re-render."""
        if event_type == "line":
            self._ingest_line(payload)  # type: ignore[arg-type]
            return True
        if event_type == "heardme":
            self._ingest_heard_me(payload)  # type: ignore[arg-type]
            return True
        if event_type == "decode":
            self._ingest_decode(payload)  # type: ignore[arg-type]
            return True
        if event_type == "qso_logged":
            self._ingest_qso_logged(payload)  # type: ignore[arg-type]
            return True
        if event_type == "band":
            if payload:
                self.current_band = str(payload)
            return False
        if event_type == "status":
            self._set_status(str(payload))
        return False

    def _check_prune(self) -> bool:
        """Run a stale-station prune if enough time has elapsed.  Returns True if anything changed."""
        now = time.time()
        if now - self.last_prune_check >= PRUNE_EVERY_SECONDS:
            self.last_prune_check = now
            return self._prune_old()
        return False

    def run(self):
        self.root.mainloop()


# ===================================================================
# Entry point
# ===================================================================


def main():
    if "DISPLAY" not in os.environ and "WAYLAND_DISPLAY" not in os.environ:
        raise SystemExit("No GUI display found. Run cqalert.py from your desktop session.")
    app = CQAlertApp()
    app.run()
