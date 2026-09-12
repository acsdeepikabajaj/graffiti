"""Graffiti wall backend (Mac + Windows).

  python3 server.py --mock 2      # 2 simulated cursors, no hardware
  python3 server.py               # real Wiimotes (Windows + DolphinBar mode 4)
  python3 server.py --bar below

WebSocket ws://localhost:8765  -> cursor stream
HTTP      http://<lan-ip>:8766 -> snapshot save + serve (QR souvenirs)
"""
import argparse, asyncio, base64, json, math, os, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets

WS_PORT, HTTP_PORT = 8765, 8766
ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "art")
os.makedirs(ART_DIR, exist_ok=True)
clients = set()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except OSError:
        return "localhost"
    finally:
        s.close()


LAN = lan_ip()


class Art(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_POST(self):
        if self.path != "/save":
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n))
        png = base64.b64decode(data["png"].split(",", 1)[1])
        name = f"art_{int(time.time())}.png"
        with open(os.path.join(ART_DIR, name), "wb") as f:
            f.write(png)
        url = f"http://{LAN}:{HTTP_PORT}/art/{name}"
        body = json.dumps({"url": url}).encode()
        self.send_response(200); self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/art/"):
            p = os.path.join(ART_DIR, os.path.basename(self.path))
            if os.path.isfile(p):
                with open(p, "rb") as f: body = f.read()
                self.send_response(200); self._cors()
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); return
        self.send_response(404); self.end_headers()


async def ws_handler(ws):
    clients.add(ws)
    try: await ws.wait_closed()
    finally: clients.discard(ws)


async def broadcast(get_state):
    while True:
        if clients:
            msg = json.dumps({"cursors": get_state()})
            await asyncio.gather(*(c.send(msg) for c in list(clients)),
                                 return_exceptions=True)
        await asyncio.sleep(1 / 60)


def mock_factory(n):
    t0 = time.time()
    def get_state():
        t = time.time() - t0; out = []
        for i in range(n):
            ph = t * 0.6 + i * 2.1
            out.append({"player": i,
                        "x": round(0.5 + 0.35 * math.cos(ph), 4),
                        "y": round(0.5 + 0.30 * math.sin(ph * 1.3), 4),
                        "visible": True, "b": int(t * 0.5 + i) % 2 == 0,
                        "a": False, "home": False, "connected": True})
        return out
    return get_state


def real_factory(bar_above):
    from wiimote import Wiimote, find_wiimote_paths
    remotes, last = [], [0.0]
    def rescan():
        known = {r.path for r in remotes}
        for p in find_wiimote_paths():
            if p not in known and len(remotes) < 4:
                w = Wiimote(p, len(remotes), sensor_bar_above=bar_above)
                try:
                    w.start(); remotes.append(w)
                    print(f"Player {w.player + 1} connected")
                except OSError as e:
                    print(f"open failed: {e}")
    rescan()
    if not remotes:
        print("No Wiimotes yet. DolphinBar on LED 4, SYNC, then 1+2 on remote. Rescanning...")
    def get_state():
        if time.time() - last[0] > 3:
            last[0] = time.time(); rescan()
        return [r.snapshot() for r in remotes]
    return get_state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", type=int, default=0)
    ap.add_argument("--bar", choices=["above", "below"], default="above")
    a = ap.parse_args()
    get_state = mock_factory(a.mock) if a.mock else real_factory(a.bar == "above")

    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Art)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"Snapshot server http://{LAN}:{HTTP_PORT} (QR souvenirs)")

    async def run():
        async with websockets.serve(ws_handler, "localhost", WS_PORT):
            print(f"Cursor stream ws://localhost:{WS_PORT} "
                  f"({'MOCK ' + str(a.mock) if a.mock else 'real Wiimotes'})")
            await broadcast(get_state)
    asyncio.run(run())


if __name__ == "__main__":
    main()
