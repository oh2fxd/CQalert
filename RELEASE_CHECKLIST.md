# Release Checklist

## Before Upload

- Confirm `cqalert.py` starts on your target desktop session
- Confirm overlay tiles appear and can arm WSJT-X
- Confirm your WSJT-X UDP settings are correct
- Confirm flag images are available on your target system
- Remove any local-only hacks or debug prints

## Repository Setup

- Create GitHub repo named `CQAlert`
- Push contents of this folder
- Add repository description:
  `Lightweight GNOME/X11 FT8 overlay for WSJT-X that shows fresh unworked CQ stations as desktop tiles and can arm WSJT-X over UDP.`
- Add topics such as:
  `hamradio`, `ft8`, `wsjtx`, `amateur-radio`, `python`, `gnome`, `x11`

## README Checks

- Confirm install instructions are accurate for your machine
- Confirm GNOME/X11 note is still correct
- Confirm Wayland caveat is acceptable
- Add screenshots if possible

## Nice Extras

- Add one screenshot of a few live tiles
- Add one short animated GIF of the overlay in use
- Add a `CHANGELOG.md` once you start iterating releases
- Tag first upload as `v0.1.0`

## Optional First Commit

```bash
git add .
git commit -m "Initial CQAlert release"
```
