#!/usr/bin/env python3
"""One-off: start DeathMarkers' deaths.json from the deaths the dashboard already placed.

Before the plugin is installed, the dashboard can only place a death when the player's save
file shows a new last-death position, so this imports those (usually a fraction of all deaths).
    python3 seed_graves.py /opt/minecraft/plugins/DeathMarkers/deaths.json
"""
import json
import os
import sys

import gen


def main(out):
    if os.path.exists(out):
        sys.exit("%s already exists; not overwriting" % out)
    data = json.load(open(os.path.join(gen.OUT, "data.json"), encoding="utf-8"))
    uuids = {p["name"]: p["uuid"] for p in data["players"]}
    graves = []
    for s in data["sessions"]:
        for d in s["deaths"]:
            w = d.get("where")
            if not w or d["name"] not in uuids:
                continue
            graves.append({"ts": d["ts"] * 1000, "uuid": uuids[d["name"]], "name": d["name"], "world": w["dim"],
                           "x": w["pos"][0], "y": w["pos"][1], "z": w["pos"][2], "message": d["text"]})
    graves.sort(key=lambda g: g["ts"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(graves, f, ensure_ascii=False, indent=2)
    print("seeded %d deaths into %s" % (len(graves), out))


if __name__ == "__main__":
    main(sys.argv[1])
