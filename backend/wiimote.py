"""Wiimote reader over HID (works with Mayflash DolphinBar mode 4 on Windows,
or a direct Bluetooth pairing). One thread per remote; exposes latest state.

Protocol reference: WiiBrew documentation for RVL-CNT-01.
"""
import threading
import time

import hid

NINTENDO_VID = 0x057E
WIIMOTE_PIDS = {0x0306, 0x0330}  # RVL-003 and Wiimote Plus (RVL-036)

# Button bits (byte1, byte2 of core report)
BTN2_B = 0x04
BTN2_A = 0x08
BTN2_HOME = 0x80
BTN1_PLUS = 0x10

IR_CAM_W = 1024.0
IR_CAM_H = 768.0


def find_wiimote_paths():
    paths = []
    for d in hid.enumerate():
        if d["vendor_id"] == NINTENDO_VID and d["product_id"] in WIIMOTE_PIDS:
            paths.append(d["path"])
    return sorted(set(paths))


class Wiimote:
    def __init__(self, path, player_index, sensor_bar_above=True):
        self.path = path
        self.player = player_index          # 0-based
        self.bar_above = sensor_bar_above   # bar above screen vs below
        self.dev = None
        self.connected = False
        # latest state (thread-written, read by server)
        self.x = 0.5        # normalized pointer 0..1 (canvas coords)
        self.y = 0.5
        self.visible = False  # sensor bar currently in view
        self.b = False
        self.a = False
        self.home = False
        self._smooth = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    # ---- output helpers (rumble bit kept 0 in byte after report id) ----
    def _send(self, data):
        self.dev.write(bytes(data))

    def _write_register(self, offset, data):
        buf = [0x16, 0x04,
               (offset >> 16) & 0xFF, (offset >> 8) & 0xFF, offset & 0xFF,
               len(data)] + list(data) + [0] * (16 - len(data))
        self._send(buf)
        time.sleep(0.05)

    def _init_ir(self):
        # LEDs = player number
        self._send([0x11, 0x10 << self.player])
        time.sleep(0.05)
        # IR camera enable (clock + logic)
        self._send([0x13, 0x04]); time.sleep(0.05)
        self._send([0x1A, 0x04]); time.sleep(0.05)
        self._write_register(0xB00030, [0x08])
        # sensitivity block 1+2 (Wii level 3 defaults)
        self._write_register(0xB00000,
                             [0x02, 0x00, 0x00, 0x71, 0x01, 0x00, 0xAA, 0x00, 0x64])
        self._write_register(0xB0001A, [0x63, 0x03])
        # mode: 3 = extended (12 IR bytes in report 0x33)
        self._write_register(0xB00033, [0x03])
        self._write_register(0xB00030, [0x08])
        # continuous reporting, mode 0x33 = core buttons + accel + 12 IR bytes
        self._send([0x12, 0x04, 0x33])
        time.sleep(0.05)

    def start(self):
        self.dev = hid.device()
        self.dev.open_path(self.path)
        self.dev.set_nonblocking(False)
        self._init_ir()
        self.connected = True
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ---- input parsing ----
    def _run(self):
        while not self._stop.is_set():
            try:
                data = self.dev.read(32, timeout_ms=200)
            except OSError:
                self.connected = False
                return
            if not data:
                continue
            if data[0] != 0x33:
                continue
            b1, b2 = data[1], data[2]
            self.b = bool(b2 & BTN2_B)
            self.a = bool(b2 & BTN2_A)
            self.home = bool(b2 & BTN2_HOME)
            dots = []
            for i in range(4):
                o = 6 + i * 3
                x = data[o] | ((data[o + 2] >> 4) & 0x3) << 8
                y = data[o + 1] | ((data[o + 2] >> 6) & 0x3) << 8
                if x == 0x3FF and y == 0x3FF:
                    continue
                dots.append((x, y))
            if dots:
                mx = sum(d[0] for d in dots) / len(dots)
                my = sum(d[1] for d in dots) / len(dots)
                # camera sees mirrored horizontally relative to pointing
                px = 1.0 - (mx / IR_CAM_W)
                py = my / IR_CAM_H
                if not self.bar_above:
                    py = 1.0 - py
                # exponential smoothing to tame hand jitter
                if self._smooth is None:
                    self._smooth = [px, py]
                else:
                    a = 0.4
                    self._smooth[0] += a * (px - self._smooth[0])
                    self._smooth[1] += a * (py - self._smooth[1])
                self.x = min(1.0, max(0.0, self._smooth[0]))
                self.y = min(1.0, max(0.0, self._smooth[1]))
                self.visible = True
            else:
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
            "connected": self.connected,
        }
