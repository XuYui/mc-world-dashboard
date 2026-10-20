"""Builds what the page shows: summary (status, players, progress), sessions, graves."""
import json
import os
import time

from . import config, saves
from .gamedata import ADV, DEFS, MAINLINE, killer_from_message, zh_id
from .titles import titles
from .util import load_json, write_atomic


# ---------- presence and sessions ----------

def presence(events, names):
    """Per-player [start, end] intervals (end None = still online) from join/quit/server events."""
    online, intervals = {}, {n: [] for n in names}
    for e in events:
        t = e["type"]
        if t in ("server_start", "server_stop"):
            for n, t0 in online.items():
                intervals[n].append([t0, e["ts"]])
            online = {}
        elif e.get("level") != config.SAVE or e.get("name") not in intervals:
            continue
        elif t == "join":
            online.setdefault(e["name"], e["ts"])
        elif t == "quit" and e["name"] in online:
            intervals[e["name"]].append([online.pop(e["name"]), e["ts"]])
    for n, t0 in online.items():
        intervals[n].append([t0, None])
    return intervals, online


def server_state(events):
    state = {"running": False, "since": None, "level": None}
    for e in events:
        if e["type"] == "server_start":
            state.update(running=False, level=e.get("level") or state["level"])
        elif e["type"] == "server_ready":
            state.update(running=True, since=e["ts"], level=e.get("level") or state["level"])
        elif e["type"] == "server_stop":
            state.update(running=False)
    return state


def death_list(events, names):
    out = []
    for e in events:
        if e["type"] != "death" or e.get("level") != config.SAVE or e.get("name") not in names:
            continue
        text = e["data"].get("message") or e["name"]
        # the plugin sends only the message; read the killer back out of it like the log importer does
        d = {"ts": int(e["ts"]), "name": e["name"], "text": text,
             "killer": e["data"].get("killer") or killer_from_message(text, names)}
        if e.get("x") is not None:
            d["where"] = {"dim": e["world"], "pos": [round(e["x"]), round(e["y"]), round(e["z"])]}
        out.append(d)
    return out


SNAP_KEYS = ["mob_kills", "mined_total", "diamond_ore", "placed", "land_cm", "water_cm", "deaths", "play_ticks"]


def update_snapshots(summaries):
    """Stats over time (one row per change), so a session's own numbers can be computed."""
    path = os.path.join(config.DATA, "snapshots.json")
    snaps = load_json(path, {})
    changed = False
    for name, (mtime, s) in summaries.items():
        row = [mtime] + [s[k] for k in SNAP_KEYS]
        lst = snaps.setdefault(name, [])
        if not lst or lst[-1][1:] != row[1:]:
            lst.append(row)
            changed = True
    if changed:
        write_atomic(path, json.dumps(snaps))
    return snaps


def session_stats(snaps, start, end, names):
    if end is None:
        return None
    out = {}
    for n in names:
        lst = snaps.get(n, [])
        before = [r for r in lst if r[0] <= start]
        after = [r for r in lst if r[0] <= end + 600]
        if not before or not after or after[-1][0] < end - 600:
            return None
        diff = {k: after[-1][i + 1] - before[-1][i + 1] for i, k in enumerate(SNAP_KEYS)}
        out[n] = {"mob_kills": diff["mob_kills"], "mined": diff["mined_total"], "diamond_ore": diff["diamond_ore"],
                  "placed": diff["placed"], "km": round((diff["land_cm"] + diff["water_cm"]) / 100000, 1)}
    return out


def headline(s):
    firsts = [a for a in s["advancements"] if a["team_first"]]
    main = [a for a in firsts if a["id"] in MAINLINE]
    if main:
        a = main[-1]
        return "%s 拿下「%s」" % (a["name"], a["title"])
    order = {"challenge": 0, "goal": 1, "task": 2}
    if firsts:
        a = sorted(firsts, key=lambda a: order.get(a["frame"], 3))[0]
        return "%s 解锁「%s」" % (a["name"], a["title"])
    if s["deaths"]:
        cnt = {}
        for d in s["deaths"]:
            cnt[d["name"]] = cnt.get(d["name"], 0) + 1
        n = max(cnt, key=cnt.get)
        if cnt[n] >= 3:
            return "%s 阵亡 %d 次" % (n, cnt[n])
    names = [p["name"] for p in s["players"]]
    return ("%d 人联机" % len(names)) if s["multi"] else ("%s 独自游玩" % names[0])


def build_sessions(intervals, deaths, adv_by_player, team_first, snaps, now):
    spans = sorted((a, b if b is not None else now, n, b is None) for n, ivs in intervals.items() for a, b in ivs)
    groups = []
    for s in spans:
        if groups and s[0] - groups[-1]["end"] <= config.MERGE_GAP:
            groups[-1]["end"] = max(groups[-1]["end"], s[1])
            groups[-1]["spans"].append(s)
        else:
            groups.append({"start": s[0], "end": s[1], "spans": [s]})
    sessions = []
    for i, g in enumerate(groups, 1):
        ongoing = any(s[3] for s in g["spans"])
        per, edges = {}, []
        for a, b, n, _ in g["spans"]:
            per[n] = per.get(n, 0) + (b - a)
            edges += [(a, 1), (b, -1)]
        cur = peak = 0
        for _, d in sorted(edges):
            cur += d
            peak = max(peak, cur)
        lo, hi = g["start"], g["end"] + 60
        adv = []
        for n, done in adv_by_player.items():
            for aid, t in done.items():
                a = ADV[aid]
                if lo - 60 <= t <= hi and a["parent"]:  # tab roots are trivial
                    adv.append({"ts": t, "name": n, "id": aid, "title": a["title"], "frame": a["frame"],
                                "team_first": team_first.get(aid) == t})
        adv.sort(key=lambda a: a["ts"])
        sess = {
            "no": i, "start": int(g["start"]), "end": None if ongoing else int(g["end"]), "ongoing": ongoing,
            "multi": peak >= 2,
            "players": [{"name": n, "secs": int(per[n])} for n in sorted(per, key=lambda n: -per[n])],
            "deaths": [d for d in deaths if lo <= d["ts"] <= hi],
            "advancements": adv,
            "stats": session_stats(snaps, g["start"], None if ongoing else g["end"], list(per)),
        }
        sess["headline"] = headline(sess)
        sessions.append(sess)
    return sessions


# ---------- everything ----------

def build(store):
    """Returns (summary, sessions newest first, graves)."""
    now = int(time.time())
    people = saves.roster()
    names = [p["name"] for p in people]

    summaries, raw, nbt, adv = {}, {}, {}, {}
    for p in people:
        stats, mtime = saves.raw_stats(p["uuid"])
        if stats is None:
            continue
        summaries[p["name"]] = (int(mtime), saves.summarize_stats(stats))
        raw[p["name"]] = stats
        nbt[p["name"]] = saves.player_nbt(p["uuid"])
        adv[p["name"]] = saves.advancements(p["uuid"])
    snaps = update_snapshots(summaries)

    team_first = {}
    for done in adv.values():
        for aid, t in done.items():
            team_first[aid] = min(t, team_first.get(aid, t))

    events = store.events()
    intervals, online = presence(events, names)
    deaths = death_list(events, set(names))
    server = server_state(events)
    sessions = build_sessions(intervals, deaths, adv, team_first, snaps, now)

    summ = {n: s for n, (_, s) in summaries.items()}
    assigned, badges = titles(raw)
    players = []
    for p in people:
        n = p["name"]
        if n not in summ:
            continue
        s = summ[n]
        causes = {}
        for d in deaths:
            if d["name"] == n:
                k = d["killer"] or d["text"].replace(n, "", 1)
                causes[k] = causes.get(k, 0) + 1
        players.append({
            "name": n, "uuid": p["uuid"],
            "title": assigned.get(n), "badges": badges[n],
            "hours": round(s["play_ticks"] / 72000, 2),
            "stats": {k: v for k, v in s.items() if k != "killed_by"},
            "killed_by": sorted(([zh_id(k), v] for k, v in s["killed_by"].items()), key=lambda x: -x[1]),
            "causes": sorted(([k, v] for k, v in causes.items()), key=lambda x: -x[1]),
            "advancements": len(adv[n]),
            "nbt": nbt.get(n),
            "online_since": int(online[n]) if n in online else None,
            "last_seen": int(max([b for a, b in intervals[n] if b is not None], default=0)) or None,
        })

    progress = {
        "total": len(ADV),
        "done": len(team_first),
        "mainline": [{"id": a, "title": ADV[a]["title"], "desc": ADV[a]["desc"], "ts": team_first.get(a)}
                     for a in MAINLINE if a in ADV],
        "all": [{"id": a["id"], "tab": a["tab"], "depth": a["depth"], "title": a["title"], "desc": a["desc"],
                 "frame": a["frame"], "ts": team_first.get(a["id"])} for a in DEFS["advancements"]],
    }

    summary = {
        "world": config.SAVE,
        "title": config.TITLE,
        "server": {"running": server["running"] and server["level"] == config.SAVE, "since": server["since"],
                   "restart": config.RESTART},
        "clock": saves.server_clock(),
        "spawn": saves.spawn(),
        "players": players,
        "progress": progress,
        "sessions_total": len(sessions),
    }
    graves = [dict(d, uuid=next((p["uuid"] for p in people if p["name"] == d["name"]), None))
              for d in deaths if d.get("where")]
    return summary, sessions[::-1], graves
