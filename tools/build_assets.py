"""Build every game-derived file the dashboard and plugin need, from YOUR OWN Minecraft client.

Nothing produced here is committed: textures, skins, language strings and the bitmap font
belong to Mojang, so each user generates them locally from a client they own.

    python tools/build_assets.py --minecraft "C:/Users/me/AppData/Roaming/.minecraft" --version 26.1.2

Outputs (all git-ignored):
    server/defs.json                    advancement tree, death-message templates, zh_cn names
    web/assets/tex/...                  block / item textures used by the page
    web/assets/heads/<skin>.png         32x32 face + hat for each of the 18 default skins
    web/assets/mcpixel.woff2            pixel font subset
    plugin/build/lang.json              zh_cn strings for the plugin's death messages
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import zipfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from buildfont import build_font  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
WEB = os.path.join(ROOT, "web")
ASSETS = os.path.join(WEB, "assets")

TEXTURES = {
    "block": ["deepslate", "dark_oak_planks", "grass_block_side", "spruce_planks", "stone_bricks",
              "polished_blackstone", "oak_planks", "bedrock", "obsidian", "nether_bricks", "end_stone"],
    "item": ["wooden_pickaxe", "iron_ingot", "diamond", "flint_and_steel", "blaze_rod", "ender_eye", "dragon_breath"],
}
LANGS = ("en_us", "zh_cn")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minecraft", required=True, help="the .minecraft directory of an installed client")
    ap.add_argument("--version", default="26.1.2", help="client version folder under versions/")
    ap.add_argument("--lang", default="zh_cn", help="display language for names and messages")
    args = ap.parse_args()

    mc = args.minecraft
    vjson = json.load(open(os.path.join(mc, "versions", args.version, args.version + ".json"), encoding="utf-8"))
    jar = zipfile.ZipFile(os.path.join(mc, "versions", args.version, args.version + ".jar"))
    index = json.load(open(os.path.join(mc, "assets", "indexes", vjson["assetIndex"]["id"] + ".json")))["objects"]

    def asset(name):
        h = index[name]["hash"]
        return open(os.path.join(mc, "assets", "objects", h[:2], h), "rb").read()

    en = json.loads(jar.read("assets/minecraft/lang/en_us.json"))
    lang = en if args.lang == "en_us" else json.loads(asset("minecraft/lang/%s.json" % args.lang))

    defs = build_defs(jar, en, lang)
    json.dump(defs, open(os.path.join(SERVER, "defs.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("defs.json: %d advancements, %d death templates" % (len(defs["advancements"]), len(defs["deaths"])))

    for kind, names in TEXTURES.items():
        os.makedirs(os.path.join(ASSETS, "tex", kind), exist_ok=True)
        for n in names:
            src = "assets/minecraft/textures/%s/%s.png" % (kind, n)
            open(os.path.join(ASSETS, "tex", kind, n + ".png"), "wb").write(jar.read(src))

    skins = [n for n in jar.namelist() if re.match(r"assets/minecraft/textures/entity/player/(slim|wide)/\w+\.png$", n)]
    os.makedirs(os.path.join(ASSETS, "heads"), exist_ok=True)
    for n in skins:
        model, name = n.split("/")[-2], n.split("/")[-1]
        head(jar.read(n)).save(os.path.join(ASSETS, "heads", "%s_%s" % (model, name)))
    print("heads: %d" % len(skins))

    # Plugin tooltips: death templates plus every entity / item / block name an argument may use.
    plugin_lang = {k: v for k, v in lang.items() if k.startswith(("death.", "entity.minecraft.", "item.minecraft.", "block.minecraft."))}
    os.makedirs(os.path.join(ROOT, "plugin", "build"), exist_ok=True)
    json.dump(plugin_lang, open(os.path.join(ROOT, "plugin", "build", "lang.json"), "w", encoding="utf-8"), ensure_ascii=False)

    # Font: every character the page can show (game names, page text, generator strings).
    text = "".join(a["title"] for a in defs["advancements"]) + "".join(defs["ids"].values())
    text += "".join(d["zh"] for d in defs["deaths"])
    for f in glob.glob(os.path.join(WEB, "*.js")) + glob.glob(os.path.join(WEB, "*.html")) + glob.glob(os.path.join(SERVER, "mcdash", "*.py")):
        text += open(f, encoding="utf-8").read()
    unifont_zip = zipfile.ZipFile(io.BytesIO(asset("minecraft/font/unifont.zip")))
    hexname = next(n for n in unifont_zip.namelist() if n.endswith(".hex"))
    count = build_font(os.path.join(ASSETS, "mcpixel.woff2"), text,
                       jar.read("assets/minecraft/textures/font/ascii.png"),
                       unifont_zip.read(hexname).decode("ascii"))
    print("mcpixel.woff2: %d glyphs, %d bytes" % (count, os.path.getsize(os.path.join(ASSETS, "mcpixel.woff2"))))


def head(skin_png, size=32):
    """Face plus hat layer, scaled up without smoothing."""
    skin = Image.open(io.BytesIO(skin_png)).convert("RGBA")
    face = skin.crop((8, 8, 16, 16))
    face.alpha_composite(skin.crop((40, 8, 48, 16)))
    return face.resize((size, size), Image.NEAREST)


def build_defs(jar, en, lang):
    def text(component):
        if isinstance(component, dict):
            key = component.get("translate")
            return lang.get(key, en.get(key, key)) if key else component.get("text", "")
        return str(component)

    advs = []
    for name in jar.namelist():
        m = re.match(r"data/minecraft/advancement/((?!recipes/).+)\.json$", name)
        if not m:
            continue
        d = json.loads(jar.read(name))
        disp = d.get("display")
        if not disp:
            continue
        advs.append({
            "id": "minecraft:" + m.group(1), "tab": m.group(1).split("/")[0], "parent": d.get("parent"),
            "title": text(disp["title"]), "desc": text(disp.get("description", "")),
            "frame": disp.get("frame", "task"), "hidden": bool(disp.get("hidden", False)),
            "icon": disp.get("icon", {}).get("id", ""),
        })

    # Depth-first per tab, like the in-game advancement tree.
    children = {}
    for a in advs:
        children.setdefault(a["parent"], []).append(a)
    for v in children.values():
        v.sort(key=lambda a: a["id"])
    ordered = []

    def walk(a, depth):
        a["depth"] = depth
        ordered.append(a)
        for c in children.get(a["id"], []):
            walk(c, depth + 1)

    for tab in ["story", "nether", "end", "adventure", "husbandry"]:
        for root in [a for a in advs if a["tab"] == tab and not a["parent"]]:
            walk(root, 0)

    # Death messages: English template -> regex (to read server logs), plus the display template.
    deaths = []
    for k, v in en.items():
        if not k.startswith("death.") or "%" not in v:
            continue
        pattern, pos = "", 0
        for part in re.split(r"(%(?:\d\$)?s)", v):
            m = re.fullmatch(r"%(?:(\d)\$)?s", part)
            if m:
                pos += 1
                pattern += "(?P<a%d>.+?)" % (int(m.group(1)) if m.group(1) else pos)
            else:
                pattern += re.escape(part)
        deaths.append({"key": k, "re": "^" + pattern + "$", "zh": lang.get(k, v), "len": len(v)})
    deaths.sort(key=lambda d: -d["len"])

    names, ids = {}, {}
    for k, v in en.items():
        m = re.match(r"^(entity|item|block)\.minecraft\.([a-z0-9_]+)$", k)
        if m:
            names.setdefault(v, lang.get(k, v))
            ids.setdefault(m.group(2), lang.get(k, v))
    blocks = sorted(k.split(".")[2] for k in en if re.match(r"^block\.minecraft\.[a-z0-9_]+$", k))
    return {"advancements": ordered, "deaths": deaths, "names": names, "blocks": blocks, "ids": ids}


if __name__ == "__main__":
    main()
