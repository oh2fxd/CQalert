"""Tests for cqalert.protocol."""

import struct
from cqalert.protocol import (
    QtStreamReader,
    qt_utf8,
    qt_bool,
    qt_qtime_ms,
    build_heartbeat_payload,
    build_replay_payload,
    build_reply_payload,
    parse_status_payload,
    parse_qso_logged_payload,
)


def test_qt_primitives():
    # String
    data = qt_utf8("Hello")
    length = struct.unpack(">I", data[:4])[0]
    assert length == 5
    assert data[4:] == b"Hello"

    # None string
    assert qt_utf8(None) == struct.pack(">I", 0xFFFFFFFF)

    # Bool
    assert qt_bool(True) == b"\x01"
    assert qt_bool(False) == b"\x00"

    # QTime ms
    assert qt_qtime_ms(12345) == struct.pack(">I", 12345)


def test_qt_stream_reader():
    stream_data = (
        b"\x01"  # u8
        + struct.pack(">I", 42)  # u32
        + struct.pack(">i", -7)  # i32
        + struct.pack(">Q", 14074000)  # u64
        + struct.pack(">d", 1.25)  # double
        + b"\x01"  # bool
        + qt_utf8("CQAlert")  # utf8
        + qt_qtime_ms(5000)  # qtime
    )
    reader = QtStreamReader(stream_data)
    assert reader.read_u8() == 1
    assert reader.read_u32() == 42
    assert reader.read_i32() == -7
    assert reader.read_u64() == 14074000
    assert reader.read_double() == 1.25
    assert reader.read_bool() is True
    assert reader.read_utf8() == "CQAlert"
    assert reader.read_qtime_ms() == 5000
    assert reader.remaining() == 0


def test_payload_builders():
    hb = build_heartbeat_payload("app1", "title1")
    assert b"app1" in hb
    assert b"title1" in hb

    replay = build_replay_payload("app1")
    assert b"app1" in replay

    reply = build_reply_payload(
        remote_id="WSJT-X",
        timestamp_ms=1000,
        snr=-5,
        delta_time=0.2,
        delta_freq=1200,
        mode="FT8",
        message="CQ OH2FXD KP39",
        low_conf=False,
        modifiers=0x02,
    )
    assert b"WSJT-X" in reply
    assert b"CQ OH2FXD KP39" in reply
    # Last byte should be modifiers
    assert reply[-1] == 0x02


def test_parse_status_payload():
    # Build a simulated status payload
    payload = (
        qt_utf8("WSJT-X-1")
        + struct.pack(">Q", 14074000)  # Dial freq
        + qt_utf8("FT8")  # Mode
        + qt_utf8("W1AW")  # DX call
        + qt_utf8("-10")  # Report
        + qt_utf8("FT8")  # Tx mode
        + qt_bool(False)  # Tx enabled
        + qt_bool(False)  # Transmitting
        + qt_bool(True)  # Decoding
        + struct.pack(">I", 1500)  # Rx df
        + struct.pack(">I", 1500)  # Tx df
        + qt_utf8("OH2FXD")  # DE call
        + qt_utf8("KP39MS")  # DE grid
        + qt_utf8("FN31")  # DX grid
    )
    reader = QtStreamReader(payload)
    status = parse_status_payload(reader)
    assert status is not None
    assert status.wsjtx_id == "WSJT-X-1"
    assert status.dial_freq_hz == 14074000
    assert status.mode == "FT8"
    assert status.dx_call == "W1AW"
    assert status.de_call == "OH2FXD"
    assert status.de_grid == "KP39MS"


def test_parse_qso_logged_payload():
    # Build simulated QSO Logged payload
    qdatetime_dummy = struct.pack(">QI B", 2460000, 12000000, 1)  # 13 bytes
    payload = (
        qt_utf8("WSJT-X-1")
        + qdatetime_dummy
        + qt_utf8("JA1ABC")  # DX call
        + qt_utf8("PM95")  # DX grid
        + struct.pack(">Q", 21074000)  # Dial freq
        + qt_utf8("FT8")  # Mode
        + qt_utf8("-05")  # Report sent
        + qt_utf8("-12")  # Report recv
    )
    reader = QtStreamReader(payload)
    qso = parse_qso_logged_payload(reader)
    assert qso is not None
    assert qso.dx_call == "JA1ABC"
    assert qso.dx_grid == "PM95"
    assert qso.dial_freq_hz == 21074000
    assert qso.report_sent == "-05"
