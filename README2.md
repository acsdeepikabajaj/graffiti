# Graffiti Wall — setup & test guide

## Files
- `backend/server.py` — WebSocket server (real Wiimotes or `--mock` mode)
- `backend/wiimote.py` — Wiimote HID driver (DolphinBar mode 4 / Bluetooth)
- `frontend/index.html` — the wall: painting, rounds, timer, interlude

## One-time setup (Windows laptop) — do TODAY
1. Install Python 3.10+ from python.org (check "Add to PATH").
2. In a terminal:
   ```
   pip3 install websockets hidapi   # (Mac: same command; hidapi only needed for real remotes)
   ```
3. Put this folder anywhere, e.g. `C:\graffiti\`.

## TEST TODAY (no DolphinBar needed)
### A. Frontend alone
Double-click `frontend/index.html`. Press keys 1–4 to pick a player color,
click-drag to paint. Timer, interlude, reset (R), and shape dock all work.

### B. Full pipeline with simulated remotes
```
cd backend
python server.py --mock 2
```
Open `frontend/index.html`. Status shows "backend connected"; two colored
cursors orbit and spray in bursts. This proves the entire WebSocket path.

### C. Projector dry run
HDMI laptop → Dukane, project onto your wall, run test B fullscreen (F11).
Check brightness/size at your planned distances.

## WHEN THE DOLPHINBAR ARRIVES
1. Plug DolphinBar into laptop USB. Press its MODE button until **LED 4**
   lights (Wii Remote Controller Emulator mode).
2. Press SYNC on the bar, then the red SYNC button inside each Wiimote's
   battery compartment (or hold 1+2). Bar LED goes solid when synced.
3. Place the bar on top of the projected image area, switch on its back
   set to TOP.
4. Run:
   ```
   python server.py            # add --bar below if bar is under the image
   ```
   Console prints "Player 1 connected" etc.
5. Open the frontend, stand back 5–6 ft, point at the wall, hold **B** to
   spray. LEDs on each remote show its player number.

## Troubleshooting
- No remotes found: confirm LED 4 on the bar; re-sync; try another USB port.
- Cursor inverted vertically: use `--bar below` (or move bar to top).
- Jittery cursor: normal at long range; smoothing is built in — reduce
  distance or raise the `a = 0.4` smoothing factor in `wiimote.py` (lower = smoother).
- Cursor drops at screen edges: stand further back so the bar stays in the
  remote's camera view.

## v2 additions
- **2 players default** (PLAYERS constant in index.html; set to 4 later).
- **Richer guide scenes**: 123 Numbers, Rocket launch, Butterfly, Castle,
  Ocean fish, Balloons — picked from the bottom dock.
- **Logo branding**: drop your logo as `frontend/logo.png` — it appears as
  a badge on the canvas and is baked into every souvenir image.
- **QR souvenir**: at 2:30 into each round the canvas is snapshotted, saved
  by the backend, and a QR appears bottom-right. Phones on the SAME Wi-Fi
  as the laptop scan it to download the artwork.
  (QR rendering needs internet once to load the QR library from CDN; the
  snapshot itself is fully local.)
- **Mac testing**: everything except real Wiimotes runs identically on
  macOS — `python3 server.py --mock 2` + open index.html.
