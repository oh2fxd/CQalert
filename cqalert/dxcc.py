"""DXCC entity resolution from cty.dat and pycountry.

Parses the WSJT-X cty.dat country file and provides fast
callsign → country / ISO-3166-1 alpha-2 lookups.
"""

import re
from typing import Optional

from cqalert.config import (
    COUNTRY_OVERRIDES,
    find_cty_path,
    clean_country_name,
)

__all__ = ["DXCCResolver"]


class DXCCResolver:
    """Resolve amateur radio callsigns to DXCC entity names and ISO codes.

    Uses cty.dat for prefix/entity mapping and pycountry as a fallback
    for ISO-3166-1 alpha-2 code resolution.
    """

    def __init__(self):
        self.prefixes: list[tuple[str, str]] = []
        self.exact_calls: dict[str, str] = {}
        self.iso_cache: dict[str, Optional[str]] = {}
        self.country_continents: dict[str, str] = {}
        self.pycountry = None
        self._load()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _load(self):
        """Parse cty.dat and build prefix/entity lookup tables."""
        path = find_cty_path()
        if not path:
            return
        current_country = None
        with path.open("r", encoding="latin1", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                if not line.strip():
                    continue
                if not line.startswith(" "):
                    current_country = self._parse_entity_header(line)
                    continue
                if not current_country:
                    continue
                self._parse_prefix_line(line, current_country)

        self.prefixes.sort(key=lambda item: len(item[0]), reverse=True)
        self._init_pycountry()

    def _parse_entity_header(self, line: str) -> Optional[str]:
        """Parse a cty.dat entity header line (e.g. 'Finland: OH: 6: EU')."""
        parts = line.split(":")
        entity = clean_country_name(parts[0].strip())
        if len(parts) >= 4:
            self.country_continents[entity] = parts[3].strip()
        return entity

    def _parse_prefix_line(self, line: str, country: str):
        """Parse a cty.dat prefix line and register all prefixes."""
        for token in line.strip().split(","):
            item = token.strip().rstrip(";")
            if not item:
                continue
            exact = item.startswith("=")
            item = item.lstrip("=*")
            item = re.split(r"[\(\[\{<~]", item)[0].strip().upper()
            if not item:
                continue
            if exact:
                self.exact_calls[item] = country
            else:
                self.prefixes.append((item, country))

    def _init_pycountry(self):
        """Try to import pycountry for ISO code lookups."""
        try:
            import pycountry  # noqa: F811

            self.pycountry = pycountry
        except Exception:
            self.pycountry = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def country_for_call(self, call: str) -> str:
        """Return the DXCC entity name for a callsign, or empty string."""
        if not call:
            return ""
        normalized = call.upper()
        # Strip leading/trailing junk from the call
        match = re.search(r"[A-Z0-9/]+", normalized)
        if not match:
            return ""
        normalized = match.group(0)

        # Handle slashed calls (e.g. SV9/OH2FXD, OH2FXD/P, OH2FXD/OH0)
        if "/" in normalized:
            parts = normalized.split("/")
            # Check if one part is a modifier like P, M, MM, AM, QRP
            clean_parts = [p for p in parts if p not in {"P", "M", "MM", "AM", "QRP", "A", "B", "R"}]
            if len(clean_parts) == 1:
                normalized = clean_parts[0]
            elif len(clean_parts) >= 2:
                # If prefix is first (e.g. SV9/OH2FXD) and is a shorter entity prefix
                first, second = clean_parts[0], clean_parts[1]
                if len(first) < len(second) and any(ch.isalpha() for ch in first):
                    # Check if first part matches a prefix
                    for prefix, country in self.prefixes:
                        if first.startswith(prefix):
                            return country
                elif len(second) < len(first) and any(ch.isalpha() for ch in second):
                    # Check if second part matches a prefix (e.g. OH2FXD/KH6 or OH2FXD/OH0)
                    for prefix, country in self.prefixes:
                        if second.startswith(prefix):
                            return country

        if normalized in self.exact_calls:
            return self.exact_calls[normalized]
        for prefix, country in self.prefixes:
            if normalized.startswith(prefix):
                return country
        return ""

    def continent_for_country(self, country: str) -> str:
        """Return continent code (EU, NA, AS, etc.) for a country entity, or empty string."""
        return self.country_continents.get(country, "")

    def iso_for_country(self, country: str) -> Optional[str]:
        """Return ISO-3166-1 alpha-2 code for a DXCC entity name."""
        if not country:
            return None
        if country in self.iso_cache:
            return self.iso_cache[country]

        iso_code = COUNTRY_OVERRIDES.get(country)
        if not iso_code and self.pycountry:
            iso_code = self._lookup_iso_via_pycountry(country)

        self.iso_cache[country] = iso_code
        return iso_code

    def _lookup_iso_via_pycountry(self, country: str) -> Optional[str]:
        """Attempt ISO code resolution via the pycountry library."""
        try:
            return self.pycountry.countries.lookup(country).alpha_2  # type: ignore
        except LookupError:
            pass
        try:
            return self.pycountry.countries.search_fuzzy(country)[0].alpha_2  # type: ignore
        except Exception:
            pass
        return None
