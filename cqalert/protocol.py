"""WSJT-X UDP protocol: Qt-style serialization and message types.

Provides low-level binary helpers for the WSJT-X UDP protocol
(magic number 0xADBCCBDA, schema 3) as well as the :class:`QtStreamReader`
for decoding incoming packets and :class:`WSJTXDecode` for parsed decode
messages.
"""

import struct
from dataclasses import dataclass
from typing import Optional

from cqalert.config import WSJTX_MAGIC, WSJTX_SCHEMA

__all__ = [
    "WSJTXDecode",
    "WSJTXStatus",
    "WSJTXQsoLogged",
    "QtStreamReader",
    "qt_utf8",
    "qt_bool",
    "qt_qtime_ms",
    "build_heartbeat_payload",
    "build_replay_payload",
    "build_reply_payload",
    "parse_status_payload",
    "parse_qso_logged_payload",
    "WSJTX_MAGIC",
    "WSJTX_SCHEMA",
]


@dataclass
class WSJTXDecode:
    """A decoded WSJT-X UDP message (type 2) with extracted call sign."""

    wsjtx_id: str
    timestamp_ms: int
    snr: int
    delta_time: float
    delta_freq: int
    mode: str
    message: str
    low_conf: bool
    is_new: bool
    call: str
    is_cq: bool
    ts: float


@dataclass
class WSJTXStatus:
    """A parsed WSJT-X Status message (type 1)."""

    wsjtx_id: str
    dial_freq_hz: int
    mode: str
    dx_call: str
    report: str
    tx_mode: str
    tx_enabled: bool
    transmitting: bool
    decoding: bool
    rx_df: int
    tx_df: int
    de_call: str
    de_grid: str
    dx_grid: str


@dataclass
class WSJTXQsoLogged:
    """A parsed WSJT-X QSO Logged message (type 5)."""

    wsjtx_id: str
    dx_call: str
    dx_grid: str
    dial_freq_hz: int
    mode: str
    report_sent: str
    report_recv: str


# ===================================================================
# Qt-style binary serialisation helpers
# ===================================================================


def qt_utf8(text: Optional[str]) -> bytes:
    """Encode *text* as a Qt-length-prefixed UTF-8 byte string."""
    if text is None:
        return struct.pack(">I", 0xFFFFFFFF)
    data = text.encode("utf-8")
    return struct.pack(">I", len(data)) + data


def qt_bool(value: bool) -> bytes:
    """Encode a boolean as a Qt-style byte."""
    return struct.pack(">B", 1 if value else 0)


def qt_qtime_ms(value: int) -> bytes:
    """Encode a QTime as milliseconds since midnight (mod 86400000)."""
    return struct.pack(">I", max(0, int(value)) % 86_400_000)


class QtStreamReader:
    """Read Qt-style binary stream from WSJT-X UDP packets."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def read(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise ValueError("Unexpected end of packet")
        chunk = self.data[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def read_u8(self) -> int:
        return struct.unpack(">B", self.read(1))[0]

    def read_u32(self) -> int:
        return struct.unpack(">I", self.read(4))[0]

    def read_i32(self) -> int:
        return struct.unpack(">i", self.read(4))[0]

    def read_u64(self) -> int:
        return struct.unpack(">Q", self.read(8))[0]

    def read_double(self) -> float:
        return struct.unpack(">d", self.read(8))[0]

    def read_bool(self) -> bool:
        return bool(struct.unpack(">B", self.read(1))[0])

    def read_utf8(self) -> str:
        length = self.read_u32()
        if length == 0xFFFFFFFF or length == 0:
            return ""
        return self.read(length).decode("utf-8", errors="ignore")

    def read_qtime_ms(self) -> int:
        return self.read_u32()

    def skip_qdatetime(self):
        """Skip a serialized Qt QDateTime (qint64 julian day + quint32 ms + quint8 timespec)."""
        if self.remaining() >= 13:
            self.read(13)


# ===================================================================
# Payload builders & parsers
# ===================================================================


def build_heartbeat_payload(app_id: str, app_title: str) -> bytes:
    """Build the payload for a WSJT-X heartbeat (type 0) message."""
    return qt_utf8(app_id) + struct.pack(">I", WSJTX_SCHEMA) + qt_utf8(app_title) + qt_utf8("1")


def build_replay_payload(app_id: str) -> bytes:
    """Build the payload for a WSJT-X replay request (type 7)."""
    return qt_utf8(app_id)


def build_reply_payload(
    remote_id: str,
    timestamp_ms: int,
    snr: int,
    delta_time: float,
    delta_freq: int,
    mode: str,
    message: str,
    low_conf: bool,
    modifiers: int = 0,
) -> bytes:
    """Build the payload for a WSJT-X reply (type 4) message."""
    return b"".join(
        [
            qt_utf8(remote_id),
            qt_qtime_ms(timestamp_ms),
            struct.pack(">i", snr),
            struct.pack(">d", delta_time),
            struct.pack(">I", delta_freq),
            qt_utf8(mode),
            qt_utf8(message),
            qt_bool(low_conf),
            struct.pack(">B", modifiers & 0xFF),
        ]
    )


def parse_status_payload(stream: QtStreamReader) -> Optional[WSJTXStatus]:
    """Parse a WSJT-X status message payload (type 1)."""
    try:
        wsjtx_id = stream.read_utf8()
        dial_freq = stream.read_u64()
        mode = stream.read_utf8()
        dx_call = stream.read_utf8()
        report = stream.read_utf8()
        tx_mode = stream.read_utf8()
        tx_enabled = stream.read_bool()
        transmitting = stream.read_bool()
        decoding = stream.read_bool()
        rx_df = stream.read_u32()
        tx_df = stream.read_u32()
        de_call = stream.read_utf8()
        de_grid = stream.read_utf8()
        dx_grid = stream.read_utf8() if stream.remaining() else ""
        return WSJTXStatus(
            wsjtx_id=wsjtx_id,
            dial_freq_hz=dial_freq,
            mode=mode,
            dx_call=dx_call,
            report=report,
            tx_mode=tx_mode,
            tx_enabled=tx_enabled,
            transmitting=transmitting,
            decoding=decoding,
            rx_df=rx_df,
            tx_df=tx_df,
            de_call=de_call,
            de_grid=de_grid,
            dx_grid=dx_grid,
        )
    except Exception:
        return None


def parse_qso_logged_payload(stream: QtStreamReader) -> Optional[WSJTXQsoLogged]:
    """Parse a WSJT-X QSO Logged message payload (type 5)."""
    try:
        wsjtx_id = stream.read_utf8()
        stream.skip_qdatetime()
        dx_call = stream.read_utf8()
        dx_grid = stream.read_utf8()
        dial_freq = stream.read_u64()
        mode = stream.read_utf8()
        report_sent = stream.read_utf8()
        report_recv = stream.read_utf8()
        return WSJTXQsoLogged(
            wsjtx_id=wsjtx_id,
            dx_call=dx_call,
            dx_grid=dx_grid,
            dial_freq_hz=dial_freq,
            mode=mode,
            report_sent=report_sent,
            report_recv=report_recv,
        )
    except Exception:
        return None
