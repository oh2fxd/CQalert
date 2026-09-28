"""Tests for cqalert.config."""

from cqalert.config import (
    band_from_freq_mhz,
    clean_country_name,
    iso_to_flag,
    load_station_config,
    load_wsjtx_udp_config,
)


def test_band_from_freq_mhz():
    assert band_from_freq_mhz(1.840) == "160m"
    assert band_from_freq_mhz(3.573) == "80m"
    assert band_from_freq_mhz(5.357) == "60m"
    assert band_from_freq_mhz(7.074) == "40m"
    assert band_from_freq_mhz(10.136) == "30m"
    assert band_from_freq_mhz(14.074) == "20m"
    assert band_from_freq_mhz(18.100) == "17m"
    assert band_from_freq_mhz(21.074) == "15m"
    assert band_from_freq_mhz(24.915) == "12m"
    assert band_from_freq_mhz(28.074) == "10m"
    assert band_from_freq_mhz(50.313) == "6m"
    assert band_from_freq_mhz(100.0) is None
    assert band_from_freq_mhz(None) is None


def test_clean_country_name():
    assert clean_country_name("  Finland  ") == "Finland"
    assert clean_country_name("Trinidad&Tobago") == "Trinidad & Tobago"


def test_iso_to_flag():
    assert iso_to_flag("fi") == "FI"
    assert iso_to_flag("US") == "US"
    assert iso_to_flag(None) == "??"
    assert iso_to_flag("XYZ") == "??"


def test_station_config_defaults():
    call, grid = load_station_config()
    assert len(call) >= 3
    assert len(grid) >= 4

    host, port, accept_udp = load_wsjtx_udp_config()
    assert isinstance(host, str)
    assert isinstance(port, int)
    assert isinstance(accept_udp, bool)
