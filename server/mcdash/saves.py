"""Read-only access to the save: players, stats, advancements, player data, clock and weather.
Results are cached per file and re-read only when the file changes."""
import glob
import os
from datetime import datetime

from . import config
from .gamedata import ADV, BLOCKS, CROPS, FOODS, LAND, ORE_POINTS, WATER
from .util import load_json, read_nbt, short

_cache = {}


def _cached(path, loader):
    """loader(path) memoized on (mtime, size); None if the file is missing or unreadable."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    try:
        value = loader(path)
    except Exception:
        return hit[1] if hit else None  # mid-write: keep the last good value
    _cache[path] = (key, value)
    return value


def save_path(*parts):
    return os.path.join(config.MC, config.SAVE, *parts)


def roster():
    """Whitelisted players who have played this save."""
    wl = load_json(os.path.join(config.MC, "whitelist.json"), [])
    have = {os.path.basename(p)[:-5] for p in glob.glob(save_path("players/stats/*.json"))}
    return [{"uuid": w["uuid"], "name": w["name"]} for w in wl if w["uuid"] in have]


def raw_stats(uuid):
    path = save_path("players/stats", uuid + ".json")
    data = _cached(path, load_json)
    return (data or {}).get("stats"), (os.path.getmtime(path) if data else None)


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


def _player_nbt(path):
    d = read_nbt(path)
    pos = d.get("Pos") or [0, 0, 0]
    last = d.get("LastDeathLocation")
    spawn = d.get("respawn")
    return {
        "saved": int(os.path.getmtime(path)),
        "health": round(d.get("Health", 0), 1),
        "food": d.get("foodLevel", 0),
        "level": d.get("XpLevel", 0),
        "dim": d.get("Dimension", "minecraft:overworld"),
        "pos": [round(pos[0]), round(pos[1]), round(pos[2])],
        "last_death": {"dim": last.get("dimension"), "pos": last.get("pos")} if last else None,
        "respawn": {"dim": spawn.get("dimension"), "pos": spawn.get("pos")} if spawn else None,
    }


def player_nbt(uuid):
    return _cached(save_path("players/data", uuid + ".dat"), _player_nbt)


def _adv_time(s):
    # "2026-10-13 20:57:28 +0800"
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z").timestamp())


def _advancements(path):
    done = {}
    for k, v in load_json(path, {}).items():
        if k in ADV and isinstance(v, dict) and v.get("done") and v.get("criteria"):
            done[k] = max(_adv_time(t) for t in v["criteria"].values())
    return done


def advancements(uuid):
    """{advancement id: unix time it was completed}"""
    return _cached(save_path("players/advancements", uuid + ".json"), _advancements) or {}


def _clock(path):
    return read_nbt(path)["data"]


def server_clock():
    d = save_path("dimensions/minecraft/overworld/data/minecraft")
    out = {}
    clocks = _cached(os.path.join(d, "world_clocks.dat"), _clock)
    if clocks and "minecraft:overworld" in clocks:
        out["ticks"] = clocks["minecraft:overworld"]["total_ticks"]
        out["saved"] = int(os.path.getmtime(os.path.join(d, "world_clocks.dat")))
    w = _cached(os.path.join(d, "weather.dat"), _clock)
    if w:
        out["weather"] = "thunder" if w.get("thundering") else "rain" if w.get("raining") else "clear"
    return out


def spawn():
    """World spawn (x, z), for centring the map."""
    level = _cached(save_path("level.dat"), read_nbt)
    try:
        pos = level["Data"]["spawn"]["pos"]
        return [pos[0], pos[2]]
    except Exception:
        return [0, 0]
