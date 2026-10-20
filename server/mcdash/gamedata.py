"""Game knowledge: names and advancements from defs.json (built from the user's own client by
tools/build_assets.py), plus hand-made groupings used for stats."""
import re

from . import config
from .util import load_json

DEFS = load_json(config.DEFS) or {"advancements": [], "deaths": [], "names": {}, "ids": {}, "blocks": []}
ADV = {a["id"]: a for a in DEFS["advancements"]}
DEATHS = [(re.compile(d["re"]), d) for d in DEFS["deaths"]]
NAMES = DEFS["names"]          # English display name -> localized
IDS = DEFS["ids"]              # registry id -> localized
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


def zh_name(s):
    return NAMES.get(s, s)


def zh_id(id_):
    return IDS.get(id_, id_)


def skin_for(uuid):
    """Same default skin the client picks for a profile without textures."""
    h = uuid.replace("-", "")
    msb, lsb = int(h[:16], 16), int(h[16:], 16)
    hilo = msb ^ lsb
    v = ((hilo >> 32) ^ hilo) & 0xFFFFFFFF
    if v >= 2 ** 31:
        v -= 2 ** 32
    return SKINS[v % len(SKINS)]
