# CQAlert

Version 0.1.0

**Author:** Mikko Lähteenmäki (oh2fxd@gmail.com)

`CQAlert` is a lightweight FT8/WSJT-X desktop overlay for showing fresh, unworked `CQ` stations as small alert tiles.

It is inspired by the "show me the interesting calls right now" part of tools like JTAlert, but it is intentionally simple:

- watches local `WSJT-X` `ALL.TXT`
- only alerts on recent `CQ`/`QRZ` spots with a grid
- only shows calls you have not already worked
- highlights wanted targets like new DXCC / new band-DXCC
- floats compact overlay tiles on the desktop
- can arm WSJT-X through the UDP control interface

## Features

- Overlay tiles instead of a big main window
- Real country flag images from local system flag files
- Age bar and "heard X ago" timer
- Distance and bearing
- Country / continent hints
- Band info
- LoTW activity hint from local WSJT-X data
- Wanted marker (`★`) and wanted reason
- Right-click snooze
- Animated WSJT-X heartbeat overlay

## Environment

`CQAlert` was built and tuned for:

- GNOME desktop
- X11 session
- Linux
- WSJT-X local install and local data files

It may also work on other X11 window managers that support always-on-top floating windows, but GNOME on X11 is the target environment.

Wayland may behave differently for:

- overlay window stacking
- focus/raise behavior
- interaction with WSJT-X window activation

## Requirements

Python packages:

- `paho-mqtt`
- `Pillow`
- `pycountry`
- `cairosvg`

System/runtime expectations:

- Python 3
- Tkinter available
- WSJT-X installed
- local WSJT-X data under `~/.local/share/WSJT-X/`
- local country file such as `/usr/share/wsjtx/cty.dat`
- local flag images such as `/usr/share/iso-flag-png`

Optional but recommended:

- `wmctrl`

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python3 cqalert.py
```

Optional band filter:

```bash
FLAG_BANDS=20m,15m python3 cqalert.py
```

## Project Layout

```text
CQAlert/
├── cqalert/
│   ├── __init__.py
│   ├── config.py
│   ├── dxcc.py
│   ├── main.py
│   ├── protocol.py
│   └── utils.py
├── tests/
│   ├── test_config.py
│   ├── test_dxcc.py
│   ├── test_protocol.py
│   └── test_utils.py
├── cqalert.py
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE
└── RELEASE_CHECKLIST.md
```

## WSJT-X Setup

In WSJT-X, make sure:

- `Accept UDP requests` is enabled if you want click-to-arm behavior
- `UDP Server` is `127.0.0.1`
- `UDP Server Port` matches your WSJT-X setting, default `2237`

`CQAlert` reads:

- `~/.local/share/WSJT-X/ALL.TXT`
- `~/.local/share/WSJT-X/wsjtx_log.adi`
- `~/.local/share/WSJT-X/lotw-user-activity.csv`
- `~/.config/WSJT-X.ini`

## Behavior

- only recent spots are shown
- only local `CQ`/`QRZ`-style decodes with a grid are used (including directed CQs like `CQ POTA`, `CQ SOTA`, `CQ NA`, etc.)
- only unworked calls are shown
- `★` is used for wanted targets like new DXCC / new band-DXCC
- left click on a tile attempts to arm/work the station in WSJT-X
- right click snoozes a tile
- clicking `×` dismisses the tile without arming WSJT-X

## Notes

- Distances come from the decoded Maidenhead grid, so bad or stale grids upstream will produce bad distances.
- State tracking is scaffolded but currently depends on future reliable state input data from incoming spots.
- GNOME/X11 overlay behavior is intentional; this is not a notification-daemon app.

## Screenshot Ideas

Useful screenshots for GitHub:

- 3 to 6 overlay tiles visible on desktop
- heartbeat overlay visible
- one starred new DXCC tile
- one tile showing bearing, age, and distance

## GitHub Description Suggestion

`CQAlert is a lightweight GNOME/X11 FT8 overlay for WSJT-X that shows fresh unworked CQ stations as desktop tiles and can arm WSJT-X over UDP.`
