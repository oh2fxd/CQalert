"""Tests for cqalert.utils."""

import math
from pathlib import Path
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
    parse_adif_calls,
)


def test_maidenhead_to_latlon():
    # KP39ms center: lat around 69.77, lon around 27.04 (Lapland)
    lat, lon = maidenhead_to_latlon("KP39MS")
    assert 69.5 < lat < 70.0
    assert 26.5 < lon < 27.5

    # 4-character grid FN42 center
    lat, lon = maidenhead_to_latlon("FN42")
    assert 42.0 < lat < 43.0
    assert -72.0 < lon < -70.0


def test_great_circle_km():
    # Distance between KP39 and FN42 (~6000 km)
    lat1, lon1 = maidenhead_to_latlon("KP39MS")
    lat2, lon2 = maidenhead_to_latlon("FN42")
    dist = great_circle_km(lat1, lon1, lat2, lon2)
    assert 5500 < dist < 6500

    # Same location should be 0
    assert great_circle_km(lat1, lon1, lat1, lon1) == 0.0


def test_bearing_and_compass():
    # North
    b = bearing_deg(0.0, 0.0, 10.0, 0.0)
    assert math.isclose(b, 0.0, abs_tol=0.1)
    assert compass_label(b) == "N"

    # East
    b = bearing_deg(0.0, 0.0, 0.0, 10.0)
    assert math.isclose(b, 90.0, abs_tol=0.1)
    assert compass_label(b) == "E"

    # South
    b = bearing_deg(10.0, 0.0, 0.0, 0.0)
    assert math.isclose(b, 180.0, abs_tol=0.1)
    assert compass_label(b) == "S"

    # West
    b = bearing_deg(0.0, 10.0, 0.0, 0.0)
    assert math.isclose(b, 270.0, abs_tol=0.1)
    assert compass_label(b) == "W"


def test_normalize_call():
    assert normalize_call("OH2FXD") == "OH2FXD"
    assert normalize_call("<AM714Z>") == "AM714Z"
    assert normalize_call("DL1EJD/P") == "DL1EJD/P"
    assert normalize_call("") == ""


def test_looks_like_call():
    assert looks_like_call("OH2FXD") is True
    assert looks_like_call("DL1EJD/P") is True
    assert looks_like_call("K1A") is True
    assert looks_like_call("W1AW") is True
    assert looks_like_call("JR2NTC/P") is True
    assert looks_like_call("SV9/OH2FXD") is True

    # Non-call tokens and modifiers
    assert looks_like_call("CQ") is False
    assert looks_like_call("QRZ") is False
    assert looks_like_call("DX") is False
    assert looks_like_call("POTA") is False
    assert looks_like_call("SOTA") is False
    assert looks_like_call("TEST") is False
    assert looks_like_call("73") is False
    assert looks_like_call("RR73") is False
    assert looks_like_call("040") is False
    assert looks_like_call("KP39") is False
    assert looks_like_call("FN42") is False


def test_extract_cq_call():
    assert extract_cq_call(["CQ", "OH2FXD", "KP39"]) == "OH2FXD"
    assert extract_cq_call(["CQ", "DX", "HZ1TT", "KL94"]) == "HZ1TT"
    assert extract_cq_call(["CQ", "POTA", "DL1EJD/P", "JO31"]) == "DL1EJD/P"
    assert extract_cq_call(["CQ", "JA", "JH1XYZ", "PM95"]) == "JH1XYZ"
    assert extract_cq_call(["CQ", "040", "K1ABC", "FN42"]) == "K1ABC"
    assert extract_cq_call(["QRZ", "HZ1TT", "KL94"]) == "HZ1TT"
    assert extract_cq_call(["CQ", "<AM714Z>", "IN80"]) == "AM714Z"
    assert extract_cq_call(["CQ", "TEST", "W1AW", "73"]) == "W1AW"


def test_parse_alltxt():
    # Standard CQ
    line = "260606_133345    14.074 Rx FT8     -4 -0.2 1681 CQ HZ1TT KL94"
    parsed = parse_alltxt(line, "OH2FXD")
    assert parsed is not None
    call, grid, snr, is_cq, freq_mhz, band = parsed
    assert call == "HZ1TT"
    assert grid == "KL94"
    assert snr == -4
    assert is_cq is True
    assert freq_mhz == 14.074
    assert band == "20m"

    # Directed CQ POTA
    pota_line = "260606_133345    14.074 Rx FT8     -9  0.3 2432 CQ POTA DL1EJD/P JO31"
    parsed_pota = parse_alltxt(pota_line, "OH2FXD")
    assert parsed_pota is not None
    assert parsed_pota[0] == "DL1EJD/P"
    assert parsed_pota[1] == "JO31"
    assert parsed_pota[3] is True

    # Non-Rx line should be ignored
    tx_line = "260606_133345    14.074 Tx FT8      0  0.0 1500 CQ OH2FXD KP39"
    assert parse_alltxt(tx_line, "OH2FXD") is None


def test_alltxt_line_ts():
    line = "260606_133345    14.074 Rx FT8     -4 -0.2 1681 CQ HZ1TT KL94"
    ts = alltxt_line_ts(line)
    assert ts is not None
    assert ts > 0


def test_parse_adif_calls(tmp_path: Path):
    adif_file = tmp_path / "test.adi"
    adif_file.write_text(
        "<call:6>OH2FXD<band:3>20m<eor>\n"
        "<call:5>W1AW<band:3>40m<eor>\n"
        "<call:6>OH2FXD<band:3>15m<eor>\n"
    )
    calls = parse_adif_calls(adif_file)
    assert calls == {"OH2FXD", "W1AW"}
