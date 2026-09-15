"""Wiimote reader over HID (DolphinBar mode 4 slots or direct Bluetooth).

v3 pointer pipeline - built to kill flicker:
- picks the best PAIR of IR dots (similar height, plausible spacing) so a
  stray reflection or lamp doesn't yank the cursor
- when one bar dot drops out, reconstructs the midpoint from the surviving
  dot + remembered separation (no more half-separation jumps)
- speed-adaptive smoothing: rock steady when hovering, responsive when sweeping
- visibility hysteresis (~150 ms) so single missed frames don't blink the cursor
"""
import threading
import time

import hid

NINTENDO_VID = 0x057E
WIIMOTE_PIDS = {0x0306, 0x0330}

BTN2_B = 0x04
BTN2_A = 0x08
BTN2_HOME = 0x80
BTN1_UP = 0x08
BTN1_DOWN = 0x04
BTN1_RIGHT = 0x02
BTN1_LEFT = 0x01

IR_W, IR_H = 1024.0, 768.0


def find_wiimote_paths():
    paths = []
    for d in hid.enumerate():
        if d["vendor_id"] == NINTENDO_VID and d["product_id"] in WIIMOTE_PIDS:
            paths.append(d["path"])
    return sorted(set(paths))


class Wiimote:
    def __init__(self, path, player_index, sensor_bar_above=True):
        self.path = path
        self.player = player_index
        self.bar_above = sensor_bar_above
        self.dev = None
        self.connected = False
        self.x = 0.5
        self.y = 0.5
        self.visible = False
        self.b = False
        self.a = False
        self.home = False
        self.up = False
        self.down = False
        self.left = False
        self.right = False
        self.sep = 0.0
        self.ndots = 0
        self._sm = None            # smoothed camera-space pointer
        self._hist = []            # raw pointer history for median filter
        self._last_pair = None     # ((lx,ly),(rx,ry)) camera space
        self._sep_px = None        # remembered dot separation (camera px)
        self._miss = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _send(self, data):
        self.dev.write(bytes(data))

    def _write_register(self, offset, data):
        buf = [0x16, 0x04,
               (offset >> 16) & 0xFF, (offset >> 8) & 0xFF, offset & 0xFF,
               len(data)] + list(data) + [0] * (16 - len(data))
        self._send(buf)
        time.sleep(0.05)

    def _init_ir(self):
        self._send([0x11, 0x10 << self.player]); time.sleep(0.05)
        self._send([0x13, 0x04]); time.sleep(0.05)
        self._send([0x1A, 0x04]); time.sleep(0.05)
        self._write_register(0xB00030, [0x08])
        self._write_register(0xB00000,
                             [0x02, 0x00, 0x00, 0x71, 0x01, 0x00, 0xAA, 0x00, 0x64])
        self._write_register(0xB0001A, [0x63, 0x03])
        self._write_register(0xB00033, [0x03])
        self._write_register(0xB00030, [0x08])
        self._send([0x12, 0x04, 0x33]); time.sleep(0.05)

    def start(self):
        self.dev = hid.device()
        self.dev.open_path(self.path)
        self.dev.set_nonblocking(False)
        self._init_ir()
        self.connected = True
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _pick_pair(self, dots):
        best, best_score = None, 1e9
        n = len(dots)
        for i in range(n):
            for j in range(i + 1, n):
                (x1, y1, s1), (x2, y2, s2) = dots[i], dots[j]
                dy = abs(y1 - y2) / IR_H
                sep = abs(x1 - x2) / IR_W
                if sep < 0.02 or sep > 0.55:
                    continue
                score = dy * 3.0
                if self._sep_px is not None:
                    score += abs(abs(x1 - x2) - self._sep_px) / IR_W
                if score < best_score:
                    best_score, best = score, (dots[i], dots[j])
        return best

    def _one_dot_mid(self, dot):
        if self._last_pair is None or self._sep_px is None:
            return None
        x, y, _ = dot
        (lx, ly), (rx, ry) = self._last_pair
        if abs(x - lx) + abs(y - ly) <= abs(x - rx) + abs(y - ry):
            return (x + self._sep_px / 2.0, y)
        return (x - self._sep_px / 2.0, y)

    def _update_pointer(self, mid):
        mx, my = mid
        px = 1.0 - (mx / IR_W)
        py = my / IR_H
        if not self.bar_above:
            py = 1.0 - py
        # median-of-3 pre-filter: kills single-frame spikes before smoothing
        self._hist.append((px, py))
        if len(self._hist) > 3:
            self._hist.pop(0)
        px = sorted(h[0] for h in self._hist)[len(self._hist) // 2]
        py = sorted(h[1] for h in self._hist)[len(self._hist) // 2]
        if self._sm is None:
            self._sm = [px, py]
        else:
            dx, dy = px - self._sm[0], py - self._sm[1]
            speed = abs(dx) + abs(dy)
            if speed < 0.005:
                pass                      # hover deadband: hold rock-steady
            else:
                # steeper response curve: mid-speed tracking (aiming at a
                # moving target) gets a much higher alpha -> less lag
                a = min(0.92, max(0.10, 0.10 + speed * 14.0))
                self._sm[0] += a * dx
                self._sm[1] += a * dy
        self.x = min(1.0, max(0.0, self._sm[0]))
        self.y = min(1.0, max(0.0, self._sm[1]))
        self.visible = True
        self._miss = 0

    def _run(self):
        while not self._stop.is_set():
            try:
                data = self.dev.read(32, timeout_ms=200)
            except OSError:
                self.connected = False
                self.visible = False
                return
            if not data or data[0] != 0x33:
                continue
            b1, b2 = data[1], data[2]
            self.b = bool(b2 & BTN2_B)
            self.a = bool(b2 & BTN2_A)
            self.home = bool(b2 & BTN2_HOME)
            self.up = bool(b1 & BTN1_UP)
            self.down = bool(b1 & BTN1_DOWN)
            self.left = bool(b1 & BTN1_LEFT)
            self.right = bool(b1 & BTN1_RIGHT)

            dots = []
            for i in range(4):
                o = 6 + i * 3
                x = data[o] | ((data[o + 2] >> 4) & 0x3) << 8
                y = data[o + 1] | ((data[o + 2] >> 6) & 0x3) << 8
                if x == 0x3FF and y == 0x3FF:
                    continue
                size = data[o + 2] & 0x0F
                dots.append((x, y, size))
            self.ndots = len(dots)

            pair = self._pick_pair(dots) if len(dots) >= 2 else None
            if pair:
                (x1, y1, _s1), (x2, y2, _s2) = pair
                if x1 > x2:
                    x1, y1, x2, y2 = x2, y2, x1, y1
                self._last_pair = ((x1, y1), (x2, y2))
                new_sep = abs(x2 - x1)
                self._sep_px = (new_sep if self._sep_px is None
                                else self._sep_px + 0.3 * (new_sep - self._sep_px))
                self.sep = self._sep_px / IR_W
                self._update_pointer(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
            elif len(dots) == 1:
                mid = self._one_dot_mid(dots[0])
                if mid:
                    self._update_pointer(mid)
                else:
                    self._update_pointer((dots[0][0], dots[0][1]))
            else:
                self._miss += 1
                if self._miss > 15:
                    self.visible = False

    def snapshot(self):
        return {
            "player": self.player,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "visible": self.visible,
            "b": self.b,
            "a": self.a,
            "home": self.home,
            "up": self.up,
            "down": self.down,
            "left": self.left,
            "right": self.right,
            "sep": round(self.sep, 4),
            "ndots": self.ndots,
            "connected": self.connected,
        }
