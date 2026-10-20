"""Titles: one per stat a player leads the group in, judged on the raw stats files."""
from .gamedata import BLOCKS, CROPS, FOODS
from .util import short


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
