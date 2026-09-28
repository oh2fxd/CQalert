#!/usr/bin/env python3
"""CQAlert - GNOME/X11 FT8 overlay for WSJT-X.

Usage:
    python3 cqalert.py

This is the entry-point script. The application lives in the ``cqalert``
package (see ``cqalert/main.py``).

Author: Mikko Lähteenmäki (oh2fxd@gmail.com)
Version: 0.1.0
"""

from cqalert.main import main

if __name__ == "__main__":
    main()
