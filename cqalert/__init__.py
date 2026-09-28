"""CQAlert - GNOME/X11 FT8 overlay for WSJT-X.

A lightweight desktop overlay for showing fresh unworked CQ stations
from FT8 decodes as small alert tiles.

Author: Mikko Lähteenmäki (oh2fxd@gmail.com)
Version: 0.1.0
"""

__version__ = "0.1.0"
__author__ = "Mikko Lähteenmäki (oh2fxd@gmail.com)"

from cqalert.main import CQAlertApp, main

__all__ = ["CQAlertApp", "main"]
