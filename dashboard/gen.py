#!/usr/bin/env python3
"""World dashboard generator.

Reads the save, the server logs and the DeathMarkers plugin's records (all read-only), and
writes data.json next to the static page in squaremap's web directory. Runs every minute
from mc-dashboard.timer as the server's user. Settings come from environment variables
(see dashboard/systemd/mc-dashboard.service).
"""
import glob, gzip, hashlib, io, json, os, re, shutil, struct, time
from datetime import datetime, timedelta, timezone

ENV = os.environ.get
MC = ENV("DASH_SERVER_DIR", "/opt/minecraft")                       # the Paper server directory
SAVE = ENV("DASH_WORLD", "world")                                   # save folder to report on
TITLE = ENV("DASH_TITLE", SAVE)                                     # name shown on the page
HOME = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HOME, "static")
STATE = ENV("DASH_STATE", os.path.join(HOME, "state"))
OUT = ENV("DASH_OUT", os.path.join(MC, "plugins/squaremap/web/dashboard"))
GRAVES = ENV("DASH_GRAVES", os.path.join(MC, "plugins/DeathMarkers/deaths.json"))
TZ = timezone(timedelta(hours=float(ENV("DASH_UTC_OFFSET", "8"))))  # timezone of the server's log timestamps
MERGE_GAP = 15 * 60  # seconds between visits that still count as one session
RESTART_HOUR, RESTART_MIN = (int(x) for x in ENV("DASH_RESTART", "04:30").split(":"))  # daily restart, shown on the page

DEFS = json.load(open(os.path.join(HOME, "defs.json"), encoding="utf-8"))
ADV = {a["id"]: a for a in DEFS["advancements"]}
DEATHS = [(re.compile(d["re"]), d) for d in DEFS["deaths"]]
NAMES = DEFS["names"]          # English display name -> Chinese
IDS = DEFS["ids"]              # registry id -> Chinese
BLOCKS = set(DEFS["blocks"])

MAINLINE = [
    "minecraft:story/mine_stone", "minecraft:story/smelt_iron", "minecraft:story/mine_diamond",
    "minecraft:story/form_obsidian", "minecraft:story/enter_the_nether", "minecraft:nether/find_fortress",
    "minecraft:nether/obtain_blaze_rod", "minecraft:story/follow_ender_eye", "minecraft:story/enter_the_end",
    "minecraft:end/kill_dragon",
]
ORE_POINTS = {
    "coal_ore": 1, "deepslate_coal_ore": 1, "copper_ore": 1, "deepslate_copper_ore": 1,
    "iron_ore": 2, "deepslate_iron_ore": 2, "lapis_ore": 2, "deepslate_lapis_ore": 2,
    "redstone_ore": 2, "deepslate_redstone_ore": 2, "gold_ore": 3, "deepslate_gold_ore": 3,
    "nether_gold_ore": 1, "nether_quartz_ore": 1, "emerald_ore": 5, "deepslate_emerald_ore": 5,
    "diamond_ore": 6, "deepslate_diamond_ore": 6, "ancient_debris": 8,
}
LAND = ["walk", "sprint", "crouch", "climb", "fly", "aviate", "horse", "pig", "strider", "minecart", "happy_ghast", "nautilus"]
WATER = ["boat", "swim", "walk_on_water", "walk_under_water"]
CROPS = {"wheat", "carrots", "potatoes", "beetroots", "melon", "pumpkin", "sugar_cane", "cocoa",
         "sweet_berry_bush", "nether_wart", "torchflower", "pitcher_plant"}
FOODS = {"apple", "mushroom_stew", "bread", "porkchop", "cooked_porkchop", "golden_apple", "enchanted_golden_apple",
         "cod", "salmon", "tropical_fish", "pufferfish", "cooked_cod", "cooked_salmon", "cookie", "melon_slice",
         "dried_kelp", "beef", "cooked_beef", "chicken", "cooked_chicken", "rotten_flesh", "spider_eye", "carrot",
         "potato", "baked_potato", "poisonous_potato", "golden_carrot", "pumpkin_pie", "rabbit", "cooked_rabbit",
         "rabbit_stew", "mutton", "cooked_mutton", "chorus_fruit", "beetroot", "beetroot_soup", "suspicious_stew",
         "sweet_berries", "glow_berries", "honey_bottle"}
SKINS = ["slim/alex", "slim/ari", "slim/efe", "slim/kai", "slim/makena", "slim/noor", "slim/steve", "slim/sunny",
         "slim/zuri", "wide/alex", "wide/ari", "wide/efe", "wide/kai", "wide/makena", "wide/noor", "wide/steve",
         "wide/sunny", "wide/zuri"]


# ---------- small helpers ----------

def read_nbt(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    f = io.BytesIO(raw)
    t = f.read(1)[0]
    f.read(struct.unpack(">H", f.read(2))[0])
    return _nbt(f, t)


def _nbt(f, t):
    u = lambda fmt, n: struct.unpack(fmt, f.read(n))[0]
    if t == 1: return u(">b", 1)
    if t == 2: return u(">h", 2)
    if t == 3: return u(">i", 4)
    if t == 4: return u(">q", 8)
    if t == 5: return u(">f", 4)
    if t == 6: return u(">d", 8)
    if t == 7: return f.read(u(">i", 4))
    if t == 8: return f.read(u(">H", 2)).decode("utf-8", "replace")
    if t == 9:
        et, n = f.read(1)[0], u(">i", 4)
        return [_nbt(f, et) for _ in range(n)]
    if t == 10:
        d = {}
        while True:
            et = f.read(1)[0]
            if et == 0:
                return d
            k = f.read(u(">H", 2)).decode("utf-8", "replace")
            d[k] = _nbt(f, et)
    if t == 11:
        n = u(">i", 4); return list(struct.unpack(">%di" % n, f.read(4 * n)))
    if t == 12:
        n = u(">i", 4); return list(struct.unpack(">%dq" % n, f.read(8 * n)))
    raise ValueError("bad nbt tag %d" % t)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def skin_for(uuid):
    """Same default skin the client picks for a profile without textures."""
    h = uuid.replace("-", "")
    msb, lsb = int(h[:16], 16), int(h[16:], 16)
    hilo = msb ^ lsb
    v = ((hilo >> 32) ^ hilo) & 0xFFFFFFFF
    if v >= 2 ** 31:
        v -= 2 ** 32
    return SKINS[v % len(SKINS)]


def adv_time(s):
    # "2026-10-13 20:57:28 +0800"
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z").timestamp())


def zh_name(s):
    return NAMES.get(s, s)


def short(id_):
    return id_.split(":", 1)[-1]


# ---------- players and save files ----------

def roster():
    wl = load_json(os.path.join(MC, "whitelist.json"), [])
    have = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(MC, SAVE, "players/stats/*.json"))}
    return [{"uuid": w["uuid"], "name": w["name"]} for w in wl if w["uuid"] in have]


def summarize_stats(s):
    c = s.get("minecraft:custom", {})
    mined = {short(k): v for k, v in s.get("minecraft:mined", {}).items()}
    used = {short(k): v for k, v in s.get("minecraft:used", {}).items()}
    g = lambda k: c.get("minecraft:" + k, 0)
    cm = lambda keys: sum(g(k + "_one_cm") for k in keys)
    return {
        "play_ticks": g("play_time"),
        "deaths": g("deaths"),
        "mob_kills": g("mob_kills"),
        "damage_dealt": g("damage_dealt"),
        "damage_taken": g("damage_taken"),
        "mined_total": sum(mined.values()),
        "ore_points": sum(ORE_POINTS.get(k, 0) * v for k, v in mined.items()),
        "diamond_ore": mined.get("diamond_ore", 0) + mined.get("deepslate_diamond_ore", 0),
        "placed": sum(v for k, v in used.items() if k in BLOCKS),
        "land_cm": cm(LAND),
        "water_cm": cm(WATER),
        "boat_cm": g("boat_one_cm"),
        "bred": g("animals_bred"),
        "fish": g("fish_caught"),
        "harvest": sum(v for k, v in mined.items() if k in CROPS),
        "eaten": sum(v for k, v in used.items() if k in FOODS) + g("eat_cake_slice"),
        "jumps": g("jump"),
        "sleeps": g("sleep_in_bed"),
        "trades": g("traded_with_villager"),
        "killed_by": {short(k): v for k, v in s.get("minecraft:killed_by", {}).items()},
    }


def player_nbt(uuid):
    path = os.path.join(MC, SAVE, "players/data", uuid + ".dat")
    try:
        d = read_nbt(path)
    except Exception:
        return None
    pos = d.get("Pos") or [0, 0, 0]
    last = d.get("LastDeathLocation")
    return {
        "saved": int(os.path.getmtime(path)),
        "health": round(d.get("Health", 0), 1),
        "food": d.get("foodLevel", 0),
        "level": d.get("XpLevel", 0),
        "dim": d.get("Dimension", "minecraft:overworld"),
        "pos": [round(pos[0]), round(pos[1]), round(pos[2])],
        "last_death": {"dim": last.get("dimension"), "pos": last.get("pos")} if last else None,
    }


def advancements(uuid):
    d = load_json(os.path.join(MC, SAVE, "players/advancements", uuid + ".json"), {})
    done = {}
    for k, v in d.items():
        if k in ADV and isinstance(v, dict) and v.get("done") and v.get("criteria"):
            done[k] = max(adv_time(t) for t in v["criteria"].values())
    return done


# ---------- logs ----------

LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\] \[Server thread/INFO\]: (.*)$")


def log_files():
    """Rotated logs plus latest.log. Rotated logs are also copied into STATE/logs, because the
    server deletes old ones and the session history is rebuilt from them on every run."""
    archive = os.path.join(STATE, "logs")
    os.makedirs(archive, exist_ok=True)
    by_name = {}
    for p in glob.glob(os.path.join(archive, "*.log.gz")) + glob.glob(os.path.join(MC, "logs/*.log.gz")):
        by_name[os.path.basename(p)] = p
    for name, p in list(by_name.items()):
        if os.path.dirname(p) != archive:
            dst = os.path.join(archive, name)
            if not os.path.exists(dst):
                shutil.copyfile(p, dst)
                os.chmod(dst, 0o640)
            by_name[name] = dst
    files = []
    for name, p in by_name.items():
        m = re.match(r"(\d{4}-\d\d-\d\d)-(\d+)\.log\.gz$", name)
        if m:
            files.append((m.group(1), int(m.group(2)), p))
    files.sort()
    out = [(d, p) for d, _, p in files]
    latest = os.path.join(MC, "logs/latest.log")
    if os.path.exists(latest):
        out.append((None, latest))
    return out


def read_lines(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def timed_lines(date, path):
    """Yield (unix_ts, message) for server-thread lines, handling midnight rollover."""
    rows = []
    for line in read_lines(path):
        m = LINE.match(line)
        if m:
            rows.append((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), m.group(4)))
    if not rows:
        return []
    if date is None:
        # latest.log has no date in its name: anchor its last line to the file's mtime.
        mt = datetime.fromtimestamp(os.path.getmtime(path), TZ)
        day = mt.date()
        if rows[-1][0] > mt.hour * 3600 + mt.minute * 60 + mt.second + 60:
            day -= timedelta(days=1)
        rolls = sum(1 for a, b in zip(rows, rows[1:]) if b[0] < a[0])
        start = day - timedelta(days=rolls)
    else:
        start = datetime.strptime(date, "%Y-%m-%d").date()
    out, day, prev = [], start, -1
    for sec, msg in rows:
        if sec < prev:
            day += timedelta(days=1)
        prev = sec
        base = datetime(day.year, day.month, day.day, tzinfo=TZ).timestamp()
        out.append((int(base) + sec, msg))
    return out


def parse_logs(names):
    """Return (presence intervals per player, deaths, server state)."""
    level = None
    online = {}          # name -> join ts
    intervals = {n: [] for n in names}
    deaths = []
    server = {"running": False, "since": None, "level": None}
    last_ts = None
    for date, path in log_files():
        for ts, msg in timed_lines(date, path):
            last_ts = ts
            if msg.startswith("Preparing level "):
                level = msg.split('"')[1] if '"' in msg else None
                server.update(running=False, level=level)
                continue
            if msg.startswith("Done (") and "For help" in msg:
                server.update(running=True, since=ts)
                continue
            if msg.startswith("Stopping server") or msg.startswith("Starting minecraft server"):
                for n, t0 in online.items():
                    intervals[n].append([t0, ts])
                online = {}
                server.update(running=False)
                continue
            if level != SAVE:
                continue
            m = re.match(r"^(\S+) (joined|left) the game$", msg)
            if m and m.group(1) in intervals:
                n = m.group(1)
                if m.group(2) == "joined":
                    online.setdefault(n, ts)
                elif n in online:
                    intervals[n].append([online.pop(n), ts])
                continue
            first = msg.split(" ", 1)[0]
            if first in intervals:
                for rx, d in DEATHS:
                    mm = rx.match(msg)
                    if mm and mm.group("a1") == first:
                        args = {k: v for k, v in mm.groupdict().items()}
                        text = d["zh"]
                        for i in range(1, 4):
                            v = args.get("a%d" % i)
                            if v is not None:
                                v = v if v in intervals else zh_name(v.strip("[]"))
                                text = text.replace("%%%d$s" % i, v)
                        text = text.replace("%s", "")
                        killer = args.get("a2")
                        deaths.append({"ts": ts, "name": first, "key": d["key"], "text": text,
                                       "killer": zh_name(killer) if killer and killer not in intervals else killer})
                        break
    for n, t0 in online.items():
        intervals[n].append([t0, None])  # still online
    server["online"] = {n: t0 for n, t0 in online.items()}
    server["last_log"] = last_ts
    return intervals, deaths, server


# ---------- sessions ----------

def build_sessions(intervals, deaths, adv_by_player, team_first, snapshots, now):
    spans = []
    for n, ivs in intervals.items():
        for a, b in ivs:
            spans.append((a, b if b is not None else now, n, b is None))
    spans.sort()
    groups = []
    for s in spans:
        if groups and s[0] - groups[-1]["end"] <= MERGE_GAP:
            g = groups[-1]
            g["end"] = max(g["end"], s[1])
            g["spans"].append(s)
        else:
            groups.append({"start": s[0], "end": s[1], "spans": [s]})
    sessions = []
    for i, g in enumerate(groups, 1):
        ongoing = any(s[3] for s in g["spans"])
        per = {}
        events = []
        for a, b, n, _ in g["spans"]:
            per[n] = per.get(n, 0) + (b - a)
            events += [(a, 1), (b, -1)]
        events.sort(key=lambda e: (e[0], e[1]))
        cur = peak = 0
        for _, d in events:
            cur += d
            peak = max(peak, cur)
        lo, hi = g["start"], g["end"] + 60
        sd = [d for d in deaths if lo <= d["ts"] <= hi]
        adv = []
        for n, done in adv_by_player.items():
            for aid, t in done.items():
                a = ADV[aid]
                if lo - 60 <= t <= hi and a["parent"]:  # tab roots are trivial
                    adv.append({"ts": t, "name": n, "id": aid, "title": a["title"], "frame": a["frame"],
                                "team_first": team_first.get(aid) == t})
        adv.sort(key=lambda a: a["ts"])
        sess = {
            "no": i, "start": g["start"], "end": None if ongoing else g["end"], "ongoing": ongoing,
            "multi": peak >= 2,
            "players": [{"name": n, "secs": per[n]} for n in sorted(per, key=lambda n: -per[n])],
            "deaths": sd, "advancements": adv,
            "stats": session_stats(snapshots, g["start"], None if ongoing else g["end"], list(per)),
        }
        sess["headline"] = headline(sess)
        sessions.append(sess)
    return sessions


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


# ---------- stats snapshots (session diffs from the deploy day on) ----------

SNAP_KEYS = ["mob_kills", "mined_total", "diamond_ore", "placed", "land_cm", "water_cm", "deaths", "play_ticks"]


def update_snapshots(summaries):
    path = os.path.join(STATE, "snapshots.json")
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


def attach_graves(deaths):
    """Exact death positions recorded by the DeathMarkers plugin, matched to log deaths by name and time."""
    graves = load_json(GRAVES, [])
    by_name = {}
    for g in graves:
        by_name.setdefault(g.get("name"), []).append(g)
    for d in deaths:
        for g in by_name.get(d["name"], []):
            if abs(g["ts"] / 1000 - d["ts"]) <= 5:
                d["where"] = {"dim": g["world"], "pos": [round(g["x"]), round(g["y"]), round(g["z"])]}
                break


def attach_death_coords(deaths, nbt_by_name):
    """Fallback for deaths before the plugin: remember each new LastDeathLocation and pin it on
    that player's latest death in the log."""
    path = os.path.join(STATE, "death_coords.json")
    known = load_json(path, {"last": {}, "pins": {}})
    changed = False
    for n, nb in nbt_by_name.items():
        ld = nb and nb.get("last_death")
        if not ld:
            continue
        sig = json.dumps(ld)
        if known["last"].get(n) != sig:
            mine = [d for d in deaths if d["name"] == n and d["ts"] <= nb["saved"] + 60]
            if mine and n in known["last"]:  # skip the very first sighting: we don't know which death it was
                known["pins"][str(mine[-1]["ts"]) + n] = ld
            known["last"][n] = sig
            changed = True
    if changed:
        write_atomic(path, json.dumps(known))
    for d in deaths:
        pin = known["pins"].get(str(d["ts"]) + d["name"])
        if pin and "where" not in d:
            d["where"] = pin


# ---------- titles ----------

def _sum(d, keys):
    return sum(d.get(k, 0) for k in keys)


def _ends(d, suffixes, exclude=()):
    return sum(v for k, v in d.items() if k.endswith(suffixes) and not k.startswith(exclude))


def title_metrics(raw):
    """Per-player numbers the titles are judged on (from the raw stats file)."""
    c = {short(k): v for k, v in raw.get("minecraft:custom", {}).items()}
    m = {short(k): v for k, v in raw.get("minecraft:mined", {}).items()}
    k = {short(x): v for x, v in raw.get("minecraft:killed", {}).items()}
    u = {short(x): v for x, v in raw.get("minecraft:used", {}).items()}
    cr = raw.get("minecraft:crafted", {})
    ore = lambda name: _sum(m, [name + "_ore", "deepslate_" + name + "_ore"])
    return {
        "logs": _ends(m, ("_log", "_wood", "_stem", "_hyphae"), exclude=("attached_", "melon", "pumpkin", "mushroom")),
        "stone": _sum(m, ["stone", "cobblestone", "deepslate", "cobbled_deepslate", "andesite", "diorite", "granite",
                          "tuff", "calcite", "sandstone", "red_sandstone", "dripstone_block"]),
        "dirt": _sum(m, ["dirt", "grass_block", "coarse_dirt", "rooted_dirt", "podzol", "mycelium", "mud", "clay",
                         "sand", "red_sand", "gravel"]),
        "nether_rock": _sum(m, ["netherrack", "basalt", "blackstone", "soul_sand", "soul_soil", "crimson_nylium",
                                "warped_nylium"]),
        "coal": ore("coal"), "copper": ore("copper"), "iron": ore("iron"),
        "gold": ore("gold") + m.get("nether_gold_ore", 0), "diamond": ore("diamond"), "emerald": ore("emerald"),
        "redstone": ore("redstone"), "lapis": ore("lapis"), "quartz": m.get("nether_quartz_ore", 0),
        "debris": m.get("ancient_debris", 0),
        "mob_kills": c.get("mob_kills", 0),
        "zombies": _sum(k, ["zombie", "husk", "drowned", "zombie_villager"]),
        "skeletons": _sum(k, ["skeleton", "stray", "bogged", "wither_skeleton"]),
        "creepers": k.get("creeper", 0),
        "spiders": _sum(k, ["spider", "cave_spider"]),
        "endermen": k.get("enderman", 0),
        "blazes": k.get("blaze", 0),
        "piglins": _sum(k, ["piglin", "zombified_piglin", "piglin_brute", "hoglin"]),
        "raiders": _sum(k, ["pillager", "vindicator", "evoker", "ravager", "witch", "vex"]),
        "livestock": _sum(k, ["sheep", "cow", "pig", "chicken", "rabbit", "mooshroom", "goat"]),
        "player_kills": c.get("player_kills", 0),
        "damage_dealt": c.get("damage_dealt", 0) // 10,
        "damage_taken": c.get("damage_taken", 0) // 10,
        "shield": c.get("damage_blocked_by_shield", 0) // 10,
        "deaths": c.get("deaths", 0),
        "fall_m": c.get("fall_one_cm", 0) // 100,
        "boat_km": c.get("boat_one_cm", 0) / 100000,
        "walk_km": c.get("walk_one_cm", 0) / 100000,
        "sprint_km": c.get("sprint_one_cm", 0) / 100000,
        "swim_km": _sum(c, ["swim_one_cm", "walk_under_water_one_cm"]) / 100000,
        "climb_m": c.get("climb_one_cm", 0) // 100,
        "aviate_km": c.get("aviate_one_cm", 0) / 100000,
        "horse_km": c.get("horse_one_cm", 0) / 100000,
        "jumps": c.get("jump", 0),
        "sneak_min": c.get("sneak_time", 0) // 1200,
        "hours": c.get("play_time", 0) / 72000,
        "sleeps": c.get("sleep_in_bed", 0),
        "bred": c.get("animals_bred", 0),
        "fish": c.get("fish_caught", 0),
        "harvest": sum(v for x, v in m.items() if x in CROPS),
        "eaten": sum(v for x, v in u.items() if x in FOODS) + c.get("eat_cake_slice", 0),
        "placed": sum(v for x, v in u.items() if x in BLOCKS),
        "torches": _sum(u, ["torch", "soul_torch", "copper_torch"]),
        "crafted": sum(cr.values()),
        "smelting": _sum(c, ["interact_with_furnace", "interact_with_blast_furnace", "interact_with_smoker"]),
        "trades": c.get("traded_with_villager", 0),
        "chests": _sum(c, ["open_chest", "open_barrel", "open_shulker_box"]),
        "brewing": c.get("interact_with_brewingstand", 0),
        "enchants": c.get("enchant_item", 0),
        "bells": c.get("bell_ring", 0),
    }


# (metric, pick, title, description with {v}); pick=min means "fewest wins".
TITLE_RULES = [
    ("logs", max, "伐木工", "砍了 {v} 块原木"),
    ("stone", max, "石匠", "挖了 {v} 块石头"),
    ("dirt", max, "挖土机", "挖了 {v} 块泥土沙砾"),
    ("nether_rock", max, "下界掘进机", "挖了 {v} 块下界岩石"),
    ("coal", max, "煤老板", "挖了 {v} 块煤矿"),
    ("copper", max, "铜匠", "挖了 {v} 块铜矿"),
    ("iron", max, "铁匠", "挖了 {v} 块铁矿"),
    ("gold", max, "淘金者", "挖了 {v} 块金矿"),
    ("diamond", max, "钻石大亨", "挖了 {v} 块钻石矿"),
    ("emerald", max, "绿宝石之王", "挖了 {v} 块绿宝石矿"),
    ("redstone", max, "红石工程师", "挖了 {v} 块红石矿"),
    ("lapis", max, "青金石学者", "挖了 {v} 块青金石矿"),
    ("quartz", max, "石英商人", "挖了 {v} 块石英矿"),
    ("debris", max, "远古残骸猎人", "挖了 {v} 块远古残骸"),
    ("mob_kills", max, "屠夫", "一共杀了 {v} 只生物"),
    ("zombies", max, "僵尸克星", "杀了 {v} 只僵尸类"),
    ("skeletons", max, "骷髅克星", "杀了 {v} 只骷髅类"),
    ("creepers", max, "拆弹专家", "杀了 {v} 只苦力怕"),
    ("spiders", max, "蜘蛛侠", "杀了 {v} 只蜘蛛"),
    ("endermen", max, "末影猎手", "杀了 {v} 只末影人"),
    ("blazes", max, "烈焰猎手", "杀了 {v} 只烈焰人"),
    ("piglins", max, "猪灵杀手", "杀了 {v} 只猪灵类"),
    ("raiders", max, "村庄守卫", "杀了 {v} 个灾厄村民和女巫"),
    ("livestock", max, "屠宰场长", "宰了 {v} 只家畜"),
    ("player_kills", max, "PK 王", "击杀了 {v} 次玩家"),
    ("damage_dealt", max, "战神", "造成 {v} 点伤害"),
    ("damage_taken", max, "肉盾", "承受 {v} 点伤害"),
    ("shield", max, "盾卫", "用盾挡下 {v} 点伤害"),
    ("deaths", max, "敢死队长", "死了 {v} 次"),
    ("deaths", min, "苟王", "只死了 {v} 次"),
    ("fall_m", max, "自由落体", "累计摔落 {v} 米"),
    ("boat_km", max, "船长", "划船 {v} km"),
    ("walk_km", max, "徒步旅行家", "步行 {v} km"),
    ("sprint_km", max, "飞毛腿", "疾跑 {v} km"),
    ("swim_km", max, "游泳健将", "游泳 {v} km"),
    ("climb_m", max, "攀岩达人", "爬梯子和藤蔓 {v} 米"),
    ("aviate_km", max, "飞行员", "鞘翅飞行 {v} km"),
    ("horse_km", max, "骑士", "骑马 {v} km"),
    ("jumps", max, "跳跳虎", "跳了 {v} 次"),
    ("sneak_min", max, "潜行大师", "潜行了 {v} 分钟"),
    ("hours", max, "肝帝", "玩了 {v} 小时"),
    ("sleeps", max, "睡神", "睡了 {v} 次觉"),
    ("bred", max, "牧场主", "繁殖了 {v} 次动物"),
    ("fish", max, "钓鱼佬", "钓了 {v} 次鱼"),
    ("harvest", max, "农夫", "收割了 {v} 次作物"),
    ("eaten", max, "吃货", "吃了 {v} 次东西"),
    ("placed", max, "建筑师", "放置了 {v} 个方块"),
    ("torches", max, "光明使者", "插了 {v} 支火把"),
    ("crafted", max, "工匠", "合成了 {v} 件物品"),
    ("smelting", max, "炉火纯青", "开了 {v} 次熔炉"),
    ("trades", max, "商人", "和村民交易 {v} 次"),
    ("chests", max, "翻箱倒柜", "开了 {v} 次箱子"),
    ("brewing", max, "药剂师", "用了 {v} 次酿造台"),
    ("enchants", max, "附魔师", "附魔了 {v} 次"),
    ("bells", max, "敲钟人", "敲了 {v} 次钟"),
]


def _fmt(v):
    if isinstance(v, float):
        return ("%.1f" % v) if v < 100 else "{:,}".format(round(v))
    return "{:,}".format(v)


def titles(raw_by_name):
    """Each rule needs one clear winner (no tie, non-zero). A player's headline title is the
    rule they win by the widest margin over the runner-up."""
    names = list(raw_by_name)
    met = {n: title_metrics(raw_by_name[n]) for n in names}
    badges = {n: [] for n in names}
    if len(names) < 2:
        return {}, badges
    for key, pick, title, why in TITLE_RULES:
        vals = sorted(((met[n][key], n) for n in names), reverse=(pick is max))
        (best, w), (second, _) = vals[0], vals[1]
        if best == second or (pick is max and best <= 0):
            continue
        margin = (best + 1) / (second + 1) if pick is max else (second + 1) / (best + 1)
        badges[w].append({"title": title, "why": why.format(v=_fmt(best)), "margin": round(margin, 3)})
    for n in names:
        badges[n].sort(key=lambda b: -b["margin"])
    assigned = {n: badges[n][0]["title"] for n in names if badges[n]}
    return assigned, badges


# ---------- main ----------

def server_clock():
    d = os.path.join(MC, SAVE, "dimensions/minecraft/overworld/data/minecraft")
    out = {}
    try:
        p = os.path.join(d, "world_clocks.dat")
        clocks = read_nbt(p)["data"]
        out["ticks"] = clocks["minecraft:overworld"]["total_ticks"]
        out["saved"] = int(os.path.getmtime(p))
    except Exception:
        pass
    try:
        w = read_nbt(os.path.join(d, "weather.dat"))["data"]
        out["weather"] = "thunder" if w.get("thundering") else "rain" if w.get("raining") else "clear"
    except Exception:
        pass
    return out


ROOT_MARK = b'name="friends-world-dashboard"'
# Tags this script adds to squaremap's page (removed and re-added whenever the files change).
MAP_TAGS = re.compile(rb'<script src="dashboard/maphook\.js[^"]*"></script>|<link rel="stylesheet" href="dashboard/map\.css[^"]*">')


def _versioned(name):
    """dashboard/<name>?v=<content hash>, so browsers fetch a file again exactly when it changes."""
    digest = hashlib.md5(open(os.path.join(STATIC, name), "rb").read()).hexdigest()[:10]
    return ("dashboard/%s?v=%s" % (name, digest)).encode()


def _write_if_changed(path, content):
    if os.path.exists(path) and open(path, "rb").read() == content:
        return
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(content)
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def sync_root():
    """Serve the dashboard at the web root and keep squaremap's own page as map.html.

    squaremap rewrites index.html when it starts (auto-update), so each run moves a
    fresh squaremap index.html to map.html and puts the dashboard back. map.html gets
    maphook.js (exposes the Leaflet map for following a player) and map.css (restyles
    squaremap's controls to match the dashboard).
    """
    web = os.path.dirname(OUT)
    index, mp = os.path.join(web, "index.html"), os.path.join(web, "map.html")
    cur = open(index, "rb").read() if os.path.exists(index) else b""
    if cur and ROOT_MARK not in cur:
        _write_if_changed(mp, cur)
    if not os.path.exists(mp):
        return
    page = MAP_TAGS.sub(b"", open(mp, "rb").read())
    tags = b'<script src="%s"></script><link rel="stylesheet" href="%s">' % (_versioned("maphook.js"), _versioned("map.css"))
    _write_if_changed(mp, page.replace(b"</head>", tags + b"</head>", 1))
    ours = open(os.path.join(STATIC, "_root.html"), "rb").read()
    for name in ("style.css", "app.js"):
        ours = ours.replace(b'"dashboard/%s"' % name.encode(), b'"%s"' % _versioned(name))
    _write_if_changed(index, ours)


def tile_index():
    """Which squaremap tiles exist, per world and zoom: {world: {zoom: [[x, z], ...]}}.
    The page's map export stitches these; the web server cannot list directories."""
    out = {}
    root = os.path.join(os.path.dirname(OUT), "tiles")
    for world in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        zooms = {}
        for z in sorted(os.listdir(os.path.join(root, world))) if os.path.isdir(os.path.join(root, world)) else []:
            if not z.isdigit():
                continue
            coords = []
            for name in os.listdir(os.path.join(root, world, z)):
                m = re.match(r"^(-?\d+)_(-?\d+)\.png$", name)
                if m:
                    coords.append([int(m.group(1)), int(m.group(2))])
            zooms[z] = sorted(coords)
        if zooms:
            out[world] = zooms
    return out


def sync_heads(people):
    """Per-player head images (their default skin) for squaremap's player markers:
    set heads-url in squaremap's config.yml to dashboard/heads/{uuid}.png."""
    out = os.path.join(OUT, "heads")
    os.makedirs(out, exist_ok=True)
    for p in people:
        src = os.path.join(STATIC, "heads", skin_for(p["uuid"]).replace("/", "_") + ".png")
        dst = os.path.join(out, p["uuid"].replace("-", "") + ".png")
        if os.path.exists(src) and (not os.path.exists(dst) or open(src, "rb").read() != open(dst, "rb").read()):
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o640)


def sync_static():
    os.makedirs(OUT, exist_ok=True)
    for root, dirs, files in os.walk(STATIC):
        rel = os.path.relpath(root, STATIC)
        dst_dir = os.path.normpath(os.path.join(OUT, rel))
        os.makedirs(dst_dir, exist_ok=True)
        for fn in files:
            if fn.startswith("_"):
                continue
            src, dst = os.path.join(root, fn), os.path.join(dst_dir, fn)
            if not os.path.exists(dst) or open(src, "rb").read() != open(dst, "rb").read():
                shutil.copyfile(src, dst)
                os.chmod(dst, 0o640)


def main():
    os.makedirs(STATE, exist_ok=True)
    sync_static()
    sync_root()
    now = int(time.time())
    people = roster()
    names = [p["name"] for p in people]
    sync_heads(people)

    summaries, nbt_by_name, adv_by_player, raw_stats = {}, {}, {}, {}
    for p in people:
        sp = os.path.join(MC, SAVE, "players/stats", p["uuid"] + ".json")
        st = load_json(sp)
        if st is None:
            continue
        summaries[p["name"]] = (int(os.path.getmtime(sp)), summarize_stats(st["stats"]))
        raw_stats[p["name"]] = st["stats"]
        nbt_by_name[p["name"]] = player_nbt(p["uuid"])
        adv_by_player[p["name"]] = advancements(p["uuid"])
    snaps = update_snapshots(summaries)

    team_first = {}
    for done in adv_by_player.values():
        for aid, t in done.items():
            team_first[aid] = min(t, team_first.get(aid, t))

    intervals, deaths, server = parse_logs(names)
    attach_graves(deaths)
    attach_death_coords(deaths, nbt_by_name)
    sessions = build_sessions(intervals, deaths, adv_by_player, team_first, snaps, now)

    summ = {n: s for n, (_, s) in summaries.items()}
    assigned, badges = titles(raw_stats)
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
        last_seen = max([b for a, b in intervals[n] if b is not None], default=None)
        players.append({
            "name": n, "uuid": p["uuid"], "skin": skin_for(p["uuid"]),
            "title": assigned.get(n), "badges": badges[n],
            "hours": round(s["play_ticks"] / 72000, 2),
            "stats": {k: v for k, v in s.items() if k != "killed_by"},
            "killed_by": sorted(([zh_name_id(k), v] for k, v in s["killed_by"].items()), key=lambda x: -x[1]),
            "causes": sorted(([k, v] for k, v in causes.items()), key=lambda x: -x[1]),
            "advancements": len(adv_by_player[n]),
            "nbt": nbt_by_name.get(n),
            "online_since": server["online"].get(n),
            "last_seen": last_seen,
        })

    progress = {
        "total": len(ADV),
        "done": len(team_first),
        "mainline": [{"id": a, "title": ADV[a]["title"], "desc": ADV[a]["desc"], "icon": ADV[a]["icon"],
                      "ts": team_first.get(a)} for a in MAINLINE],
        "all": [{"id": a["id"], "tab": a["tab"], "depth": a["depth"], "title": a["title"], "desc": a["desc"],
                 "frame": a["frame"], "ts": team_first.get(a["id"])} for a in DEFS["advancements"]],
    }

    data = {
        "generated": now,
        "world": SAVE,
        "title": TITLE,
        "server": {"running": server["running"] and server["level"] == SAVE, "since": server["since"],
                   "restart": "%02d:%02d" % (RESTART_HOUR, RESTART_MIN)},
        "clock": server_clock(),
        "players": players,
        "progress": progress,
        "sessions": sessions[::-1],
        "first_day": sessions[0]["start"] if sessions else None,
        "tiles": tile_index(),
        "fullmap": load_json(os.path.join(OUT, "fullmap", "index.json"), {}),  # made by fullmap.py
    }
    write_atomic(os.path.join(OUT, "data.json"), json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def zh_name_id(id_):
    return IDS.get(id_, id_)


if __name__ == "__main__":
    main()
