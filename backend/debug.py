import time
import hid
from wiimote import Wiimote, find_wiimote_paths

print("All HID devices with 'Nintendo' or vendor 057e:")
for d in hid.enumerate():
    if d["vendor_id"] == 0x057E or "nintendo" in (d.get("product_string") or "").lower():
        print(" ", hex(d["vendor_id"]), hex(d["product_id"]), d.get("product_string"), d["path"])

paths = find_wiimote_paths()
print(f"{len(paths)} wiimote path(s) found")
remotes = []
for i, p in enumerate(paths):
    w = Wiimote(p, i)
    w.start()
    remotes.append(w)
while remotes:
    for w in remotes:
        s = w.snapshot()
        print(f"P{s['player']+1} visible={s['visible']} x={s['x']:.2f} y={s['y']:.2f} B={s['b']} A={s['a']}")
    time.sleep(0.5)
print("No remotes found - nothing to poll.")
