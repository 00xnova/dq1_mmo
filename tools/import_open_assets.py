#!/usr/bin/env python3
"""
Import open-source (Kenney CC0) art + generate license-clean SVG enemy placeholders.

Usage (from repo root):
  python3 tools/import_open_assets.py [--kenney-dir /path/to/extracted]
  python3 tools/import_open_assets.py --svg-only   # no Kenney re-crop; regen enemies only

Outputs under client/assets/:
  src/kenney/*.png     16×16 masters (CC0)
  tiles/*.png          40×40 map tiles
  sprites/heroes/*     player sprites
  sprites/enemies/*    one PNG per enemy id in shared/dq1_data.json
  svg/enemies/*        SVG sources for placeholders (easy to replace)
  ui/icon_sword.png

Drop your own PNGs over anything; filenames are the contract.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "client" / "assets"
KENNEY_OUT = ASSETS / "src" / "kenney"
DATA = ROOT / "shared" / "dq1_data.json"

# Tiny Dungeon tile indices (16×16) — Kenney CC0
TD = {
    "dungeon_floor": 1,
    "hero_mage": 84,
    "hero_other": 86,
    "hero": 97,
    "icon_sword": 105,
    "enemy_slime": 108,
    "enemy_flesh": 109,
    "enemy_crab": 110,
    "enemy_spider_brown": 120,
    "enemy_skull": 121,
    "enemy_spider": 122,
    "enemy_snake": 123,
    "enemy_rat": 124,
    "knight_iron": 96,
    "knight_steel": 97,
    "knight_gold": 98,
    "chest_mimic": 93,
}

# Tiny Town / Urban / Roguelike crops are applied when those packs are present
TILE_SOURCES = {
    "field": ("roguelike", "grass"),  # special crop from spritesheet
    "wall": ("tiny-town", 49),
    "town": ("tiny-town", 43),
    "water": ("urban", 175),
    "dungeon": ("tiny-dungeon", 1),
}

# Map each game enemy_id → (base_key, optional RGB multiply tint or None)
# base_key is a key in TD or "svg:<archetype>"
ENEMY_MAP: dict[str, tuple[str, tuple[float, float, float] | None]] = {
    # slimes — Kenney green blob + tints
    "slime": ("enemy_slime", None),
    "red_slime": ("enemy_slime", (1.35, 0.35, 0.35)),
    "metal_slime": ("enemy_slime", (0.75, 0.95, 1.15)),
    # scorpions / crustaceans
    "scorpion": ("enemy_crab", None),
    "metal_scorpion": ("enemy_crab", (0.7, 0.85, 1.1)),
    "rogue_scorpion": ("enemy_crab", (0.55, 0.9, 0.55)),
    # undead / spectral
    "skeleton": ("enemy_skull", None),
    "wraith": ("enemy_skull", (0.65, 0.55, 0.95)),
    "wraith_knight": ("enemy_skull", (0.85, 0.75, 0.55)),
    "ghost": ("enemy_skull", (0.75, 0.95, 0.9)),
    "specter": ("enemy_skull", (0.55, 0.75, 1.0)),
    "poltergeist": ("enemy_skull", (0.95, 0.7, 0.95)),
    # beasts
    "wolf": ("enemy_rat", (0.55, 0.55, 0.6)),
    "wolflord": ("enemy_rat", (0.75, 0.55, 0.45)),
    "werewolf": ("enemy_flesh", (0.7, 0.55, 0.55)),
    # constructs
    "golem": ("enemy_flesh", (0.65, 0.65, 0.7)),
    "stoneman": ("enemy_flesh", (0.55, 0.55, 0.58)),
    "goldman": ("enemy_flesh", (1.25, 1.05, 0.35)),
    # knights / humanoids (Tiny Dungeon characters)
    "knight": ("knight_steel", None),
    "armored_knight": ("knight_iron", None),
    "axe_knight": ("knight_gold", (1.1, 0.85, 0.55)),
    "demon_knight": ("knight_iron", (0.85, 0.35, 0.45)),
    # casters
    "magician": ("hero_mage", None),
    "wizard": ("hero_mage", (0.55, 0.55, 1.15)),
    "warlock": ("hero_mage", (0.9, 0.35, 0.85)),
    "drollmagi": ("hero_mage", (0.45, 0.95, 0.55)),
    # everything else → SVG archetype placeholders
    "drakee": ("svg:drake", (0.45, 0.75, 0.95)),
    "drakeema": ("svg:drake", (0.85, 0.55, 0.95)),
    "magidrakee": ("svg:drake", (0.55, 0.95, 0.65)),
    "droll": ("svg:blob", (0.55, 0.85, 0.55)),
    "druin": ("svg:beast", (0.75, 0.55, 0.45)),
    "druinlord": ("svg:beast", (0.55, 0.35, 0.55)),
    "blue_dragon": ("svg:dragon", (0.35, 0.55, 0.95)),
    "green_dragon": ("svg:dragon", (0.35, 0.85, 0.45)),
    "red_dragon": ("svg:dragon", (0.95, 0.35, 0.3)),
    "dragonlord": ("svg:dragon", (0.55, 0.25, 0.55)),
    "dragonlord_true": ("svg:dragon", (0.95, 0.25, 0.2)),
    "wyvern": ("svg:wyvern", (0.55, 0.75, 0.55)),
    "magiwyvern": ("svg:wyvern", (0.65, 0.45, 0.95)),
    "starwyvern": ("svg:wyvern", (0.95, 0.85, 0.35)),
}


def nn_resize(im: Image.Image, size: int) -> Image.Image:
    return im.convert("RGBA").resize((size, size), Image.NEAREST)


def tint_rgba(im: Image.Image, rgb_mul: tuple[float, float, float] | None) -> Image.Image:
    if not rgb_mul:
        return im.convert("RGBA")
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    r_m, g_m, b_m = rgb_mul
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # keep outline (very dark) mostly intact
            if r + g + b < 90:
                continue
            nr = min(255, int(r * r_m))
            ng = min(255, int(g * g_m))
            nb = min(255, int(b * b_m))
            px[x, y] = (nr, ng, nb, a)
    return im


def crop_tile(pack_dir: Path, index: int) -> Image.Image:
    path = pack_dir / "Tiles" / f"tile_{index:04d}.png"
    if not path.exists():
        # tiny-dungeon uses unpadded sometimes? try both
        path = pack_dir / "Tiles" / f"tile_{index}.png"
    if not path.exists():
        raise FileNotFoundError(path)
    return Image.open(path).convert("RGBA")


def crop_roguelike_grass(pack_dir: Path) -> Image.Image:
    """Roguelike RPG pack is a spritesheet; grab a grass 16×16."""
    sheet = pack_dir / "Spritesheet" / "roguelikeSheet_transparent.png"
    if not sheet.exists():
        raise FileNotFoundError(sheet)
    im = Image.open(sheet).convert("RGBA")
    # Common layout: 16×16 tiles, 1px margin — grass near top-left variants
    # Try known grass coords; fall back to (1,1)
    # spritesheetInfo often: tile size 16, margin 1, spacing 1
    tw, margin, spacing = 16, 1, 1

    def at(col: int, row: int) -> Image.Image:
        x = margin + col * (tw + spacing)
        y = margin + row * (tw + spacing)
        return im.crop((x, y, x + tw, y + tw))

    # row0 has grass variants in this pack
    for col, row in [(5, 0), (0, 0), (1, 0), (6, 0)]:
        tile = at(col, row)
        # reject mostly transparent
        alpha = sum(1 for p in tile.get_flattened_data() if p[3] > 10)
        if alpha > 40:
            return tile
    return at(0, 0)


def crop_urban_water(pack_dir: Path, index: int = 175) -> Image.Image:
    path = pack_dir / "Tiles" / f"tile_{index:04d}.png"
    if path.exists():
        return Image.open(path).convert("RGBA")
    # fallback any water-ish tile
    tiles = sorted((pack_dir / "Tiles").glob("tile_*.png"))
    if tiles:
        return Image.open(tiles[min(len(tiles) - 1, index)]).convert("RGBA")
    raise FileNotFoundError("urban water tile")


def ensure_dirs() -> None:
    for p in (
        KENNEY_OUT,
        ASSETS / "tiles",
        ASSETS / "sprites" / "heroes",
        ASSETS / "sprites" / "enemies",
        ASSETS / "svg" / "enemies",
        ASSETS / "ui",
    ):
        p.mkdir(parents=True, exist_ok=True)


def write_svg_enemy(path: Path, archetype: str, label: str, tint: tuple[float, float, float] | None) -> None:
    """Crisp pixel-ish SVG placeholders — project-owned, free to replace."""
    t = tint or (0.7, 0.7, 0.75)
    r = int(min(255, 80 + 150 * t[0]))
    g = int(min(255, 80 + 150 * t[1]))
    b = int(min(255, 80 + 150 * t[2]))
    fill = f"#{r:02x}{g:02x}{b:02x}"
    dark = f"#{max(0,r//3):02x}{max(0,g//3):02x}{max(0,b//3):02x}"
    light = f"#{min(255,r+40):02x}{min(255,g+40):02x}{min(255,b+40):02x}"
    eye = "#1a1010"
    short = (label.replace("_", " ")[:14]).title()

    if archetype == "slime" or archetype == "blob":
        body = f'''
  <ellipse cx="64" cy="82" rx="40" ry="28" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="50" cy="72" rx="5" ry="7" fill="{eye}"/>
  <ellipse cx="78" cy="72" rx="5" ry="7" fill="{eye}"/>
  <ellipse cx="48" cy="68" rx="2" ry="2" fill="#fff" opacity="0.7"/>
  <ellipse cx="76" cy="68" rx="2" ry="2" fill="#fff" opacity="0.7"/>
'''
    elif archetype == "drake":
        body = f'''
  <ellipse cx="64" cy="88" rx="22" ry="10" fill="{dark}" opacity="0.35"/>
  <ellipse cx="64" cy="70" rx="28" ry="22" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="88" cy="58" rx="16" ry="12" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <polygon points="100,52 118,48 104,62" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="94" cy="54" rx="3" ry="3" fill="{eye}"/>
  <rect x="40" y="78" width="8" height="14" fill="{dark}"/>
  <rect x="56" y="80" width="8" height="14" fill="{dark}"/>
  <rect x="72" y="78" width="8" height="14" fill="{dark}"/>
'''
    elif archetype == "dragon":
        body = f'''
  <ellipse cx="64" cy="100" rx="30" ry="10" fill="{dark}" opacity="0.3"/>
  <polygon points="20,70 8,40 28,55" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <polygon points="108,70 120,40 100,55" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="64" cy="72" rx="34" ry="26" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="64" cy="48" rx="18" ry="16" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <polygon points="50,38 44,18 58,32" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <polygon points="78,38 84,18 70,32" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="56" cy="48" rx="3" ry="4" fill="{eye}"/>
  <ellipse cx="72" cy="48" rx="3" ry="4" fill="{eye}"/>
  <polygon points="60,56 64,62 68,56" fill="{dark}"/>
'''
    elif archetype == "wyvern":
        body = f'''
  <ellipse cx="64" cy="96" rx="24" ry="8" fill="{dark}" opacity="0.3"/>
  <polygon points="24,60 4,36 36,50" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <polygon points="104,60 124,36 92,50" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="64" cy="68" rx="22" ry="28" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="64" cy="42" rx="14" ry="12" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="58" cy="40" rx="2.5" ry="3" fill="{eye}"/>
  <ellipse cx="70" cy="40" rx="2.5" ry="3" fill="{eye}"/>
  <polygon points="64,90 58,118 70,118" fill="{fill}" stroke="{dark}" stroke-width="2"/>
'''
    elif archetype == "beast":
        body = f'''
  <ellipse cx="64" cy="96" rx="28" ry="10" fill="{dark}" opacity="0.3"/>
  <ellipse cx="64" cy="72" rx="32" ry="24" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="64" cy="48" rx="20" ry="16" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <polygon points="48,40 42,24 54,36" fill="{dark}"/>
  <polygon points="80,40 86,24 74,36" fill="{dark}"/>
  <ellipse cx="56" cy="48" rx="3" ry="3" fill="{eye}"/>
  <ellipse cx="72" cy="48" rx="3" ry="3" fill="{eye}"/>
  <rect x="40" y="84" width="10" height="16" fill="{dark}"/>
  <rect x="78" y="84" width="10" height="16" fill="{dark}"/>
'''
    else:
        body = f'''
  <circle cx="64" cy="64" r="36" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <circle cx="52" cy="58" r="5" fill="{eye}"/>
  <circle cx="76" cy="58" r="5" fill="{eye}"/>
'''

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128"
     shape-rendering="geometricPrecision" role="img" aria-label="{label}">
  <!-- Project placeholder — replace client/assets/sprites/enemies/{label}.png anytime -->
  <rect width="128" height="128" fill="none"/>
  {body}
  <text x="64" y="122" text-anchor="middle" font-family="monospace" font-size="10" fill="#333">{short}</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")


def svg_to_png(svg_path: Path, png_path: Path, size: int = 96) -> bool:
    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        subprocess.run(
            [rsvg, "-w", str(size), "-h", str(size), str(svg_path), "-o", str(png_path)],
            check=True,
        )
        return True
    # Pillow cannot read SVG; try magick
    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        subprocess.run(
            [magick, "-background", "none", str(svg_path), "-resize", f"{size}x{size}", str(png_path)],
            check=True,
        )
        return True
    print(f"warn: cannot rasterize {svg_path.name} (need rsvg-convert or ImageMagick)", file=sys.stderr)
    return False


def load_enemy_ids() -> list[str]:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    enemies = data.get("enemies") or {}
    if isinstance(enemies, dict):
        return sorted(enemies.keys())
    return sorted(e.get("id") or e.get("name") for e in enemies)


def find_kenney_dir(explicit: Path | None) -> Path | None:
    if explicit and explicit.is_dir():
        return explicit
    candidates = [
        Path("/tmp/kenney_dl/extracted"),
        ROOT / "tools" / "_kenney_cache",
        Path.home() / "Downloads" / "kenney",
    ]
    for c in candidates:
        if (c / "tiny-dungeon").is_dir() or (c / "Tiles").is_dir():
            return c
    return None


def vendor_kenney_masters(kdir: Path) -> dict[str, Image.Image]:
    """Crop + save 16×16 masters into src/kenney; return name→Image."""
    masters: dict[str, Image.Image] = {}
    td = kdir / "tiny-dungeon"
    if not td.is_dir():
        # maybe kdir itself is tiny-dungeon
        if (kdir / "Tiles").is_dir():
            td = kdir
        else:
            print("warn: tiny-dungeon not found under", kdir)
            return masters

    for name, idx in TD.items():
        try:
            im = crop_tile(td, idx)
            masters[name] = im
            im.save(KENNEY_OUT / f"{name}.png")
        except FileNotFoundError as e:
            print("skip", name, e)

    # map tiles
    try:
        if (kdir / "roguelike").is_dir():
            field = crop_roguelike_grass(kdir / "roguelike")
            masters["field"] = field
            field.save(KENNEY_OUT / "field.png")
        elif (KENNEY_OUT / "field.png").exists():
            masters["field"] = Image.open(KENNEY_OUT / "field.png")
    except Exception as e:
        print("field crop:", e)

    try:
        tt = kdir / "tiny-town"
        if tt.is_dir():
            for name, idx in (("wall", 49), ("town", 43)):
                im = crop_tile(tt, idx)
                masters[name] = im
                im.save(KENNEY_OUT / f"{name}.png")
    except Exception as e:
        print("town tiles:", e)

    try:
        urban = kdir / "urban"
        if urban.is_dir():
            water = crop_urban_water(urban, 175)
            masters["water"] = water
            water.save(KENNEY_OUT / "water.png")
    except Exception as e:
        print("water:", e)

    if "dungeon_floor" in masters:
        masters["dungeon"] = masters["dungeon_floor"]
        masters["dungeon"].save(KENNEY_OUT / "dungeon.png")

    # convenience aliases used by gen script
    for src, dst in (
        ("hero", "hero.png"),
        ("hero_other", "hero_other.png"),
        ("hero_mage", "hero_mage.png"),
        ("icon_sword", "icon_sword.png"),
        ("enemy_slime", "enemy_slime.png"),
        ("enemy_skull", "enemy_skull.png"),
        ("enemy_spider", "enemy_spider.png"),
    ):
        if src in masters:
            masters[src].save(KENNEY_OUT / dst)

    # License note
    (KENNEY_OUT / "LICENSE.txt").write_text(
        """Kenney asset crops used by dq1_mmo

Source packs (all Creative Commons Zero / CC0):
  https://kenney.nl/assets/tiny-town
  https://kenney.nl/assets/tiny-dungeon
  https://kenney.nl/assets/rpg-urban-pack
  https://kenney.nl/assets/roguelike-rpg-pack

Author: Kenney Vleugels (www.kenney.nl)
License: https://creativecommons.org/publicdomain/zero/1.0/

You may use these graphics in personal and commercial projects.
Credit (Kenney or www.kenney.nl) would be nice but is not mandatory.

Enemy combat sprites may also use generated SVG placeholders under svg/enemies/
(project-owned). Replace any file under sprites/ freely.
""",
        encoding="utf-8",
    )
    return masters


def load_existing_masters() -> dict[str, Image.Image]:
    masters = {}
    if not KENNEY_OUT.is_dir():
        return masters
    for p in KENNEY_OUT.glob("*.png"):
        masters[p.stem] = Image.open(p).convert("RGBA")
    return masters


def export_game_assets(masters: dict[str, Image.Image]) -> None:
    # tiles
    for name in ("field", "wall", "town", "water", "dungeon"):
        src = masters.get(name) or masters.get("dungeon_floor")
        if src is None and (KENNEY_OUT / f"{name}.png").exists():
            src = Image.open(KENNEY_OUT / f"{name}.png")
        if src is not None:
            nn_resize(src, 40).save(ASSETS / "tiles" / f"{name}.png")
            print("tile", name)

    # heroes
    if "hero" in masters:
        nn_resize(masters["hero"], 40).save(ASSETS / "sprites" / "heroes" / "hero.png")
        nn_resize(masters["hero"], 80).save(ASSETS / "sprites" / "heroes" / "hero_battle.png")
    if "hero_other" in masters:
        nn_resize(masters["hero_other"], 40).save(ASSETS / "sprites" / "heroes" / "other.png")
    if "icon_sword" in masters:
        nn_resize(masters["icon_sword"], 32).save(ASSETS / "ui" / "icon_sword.png")
    print("heroes/ui ok")


def export_enemies(masters: dict[str, Image.Image], enemy_ids: list[str]) -> None:
    svg_dir = ASSETS / "svg" / "enemies"
    out_dir = ASSETS / "sprites" / "enemies"
    n_kenney = n_svg = 0

    for eid in enemy_ids:
        base, tint = ENEMY_MAP.get(eid, ("svg:blob", None))
        dest = out_dir / f"{eid}.png"

        if base.startswith("svg:"):
            arch = base.split(":", 1)[1]
            svg_path = svg_dir / f"{eid}.svg"
            write_svg_enemy(svg_path, arch, eid, tint)
            if svg_to_png(svg_path, dest, 96):
                n_svg += 1
            continue

        im = masters.get(base)
        if im is None:
            # fallback SVG blob
            svg_path = svg_dir / f"{eid}.svg"
            write_svg_enemy(svg_path, "blob", eid, tint)
            if svg_to_png(svg_path, dest, 96):
                n_svg += 1
            continue

        im = tint_rgba(im, tint)
        nn_resize(im, 96).save(dest)
        n_kenney += 1

    print(f"enemies: {n_kenney} from Kenney CC0, {n_svg} SVG placeholders (total {len(enemy_ids)})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kenney-dir", type=Path, default=None, help="Extracted Kenney packs root")
    ap.add_argument("--svg-only", action="store_true", help="Only regenerate SVG enemies; keep tiles/heroes")
    ap.add_argument("--download", action="store_true", help="Download Kenney packs to tools/_kenney_cache")
    args = ap.parse_args()

    ensure_dirs()
    enemy_ids = load_enemy_ids()
    print(f"game enemies: {len(enemy_ids)}")

    if args.download:
        cache = ROOT / "tools" / "_kenney_cache"
        cache.mkdir(parents=True, exist_ok=True)
        packs = {
            "tiny-dungeon": "https://kenney.nl/media/pages/assets/tiny-dungeon/f8422efb44-1674742415/kenney_tiny-dungeon.zip",
            "tiny-town": "https://kenney.nl/media/pages/assets/tiny-town/a415fbeb49-1735736916/kenney_tiny-town.zip",
            "roguelike": "https://kenney.nl/media/pages/assets/roguelike-rpg-pack/12c03cd78b-1677697420/kenney_roguelike-rpg-pack.zip",
            "urban": "https://kenney.nl/media/pages/assets/rpg-urban-pack/0a097d1dc7-1677578575/kenney_rpg-urban-pack.zip",
        }
        import urllib.request
        import zipfile

        for name, url in packs.items():
            zpath = cache / f"{name}.zip"
            dest = cache / name
            if not dest.is_dir():
                print("download", name)
                urllib.request.urlretrieve(url, zpath)
                dest.mkdir(exist_ok=True)
                with zipfile.ZipFile(zpath) as zf:
                    zf.extractall(dest)
        args.kenney_dir = cache

    masters: dict[str, Image.Image] = {}
    if not args.svg_only:
        kdir = find_kenney_dir(args.kenney_dir)
        if kdir:
            print("using Kenney packs at", kdir)
            masters = vendor_kenney_masters(kdir)
        else:
            print("no Kenney extract found; using existing src/kenney masters if present")
            masters = load_existing_masters()
        if masters:
            export_game_assets(masters)
        else:
            print("warn: no Kenney masters — tiles/heroes left unchanged")
    else:
        masters = load_existing_masters()

    # Always ensure masters for enemy mapping
    if not masters:
        masters = load_existing_masters()
    export_enemies(masters, enemy_ids)

    # Prune leftover enemy PNGs not in the DQ1 roster? Keep extras for future content.
    print("done →", ASSETS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
