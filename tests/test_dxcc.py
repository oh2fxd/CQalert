"""Tests for cqalert.dxcc."""

from cqalert.dxcc import DXCCResolver


def test_dxcc_resolution():
    dxcc = DXCCResolver()

    # If cty.dat is present on system, test real lookups
    if dxcc.prefixes:
        # Standard Finnish call
        assert dxcc.country_for_call("OH2FXD") == "Finland"
        # Standard US call
        assert dxcc.country_for_call("W1AW") in {"United States", "United States of America"}
        # German call
        assert dxcc.country_for_call("DL1EJD") in {"Fed. Rep. of Germany", "Germany"}
        # Japanese call
        assert dxcc.country_for_call("JA1ABC") == "Japan"

        # Slashed portable call
        assert dxcc.country_for_call("DL1EJD/P") in {"Fed. Rep. of Germany", "Germany"}

        # Crete operation: SV9/OH2FXD
        assert dxcc.country_for_call("SV9/OH2FXD") == "Crete"

        # Continents
        assert dxcc.continent_for_country("Finland") == "EU"
        assert dxcc.continent_for_country("Japan") == "AS"

    # ISO codes
    assert dxcc.iso_for_country("Finland") == "FI"
    assert dxcc.iso_for_country("Fed. Rep. of Germany") == "DE"
    assert dxcc.iso_for_country("United States") == "US"
    assert dxcc.iso_for_country("Aland Islands") == "AX"
    assert dxcc.iso_for_country("Trinidad & Tobago") == "TT"
