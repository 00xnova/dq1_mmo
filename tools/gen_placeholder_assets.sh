#!/usr/bin/env bash
# Regenerate game-size PNGs from vendored Kenney CC0 sources + SVG enemy placeholders.
# Prefer: python3 tools/import_open_assets.py
# This shell script remains as a thin wrapper / offline scale path.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ASSETS="$ROOT/client/assets"
KENNEY="$ASSETS/src/kenney"

# Prefer the Python importer (Kenney mapping + SVG enemies for full roster)
if command -v python3 >/dev/null 2>&1; then
  if python3 -c "from PIL import Image" 2>/dev/null; then
    if [[ "${1:-}" == "--download" ]]; then
      exec python3 "$ROOT/tools/import_open_assets.py" --download
    fi
    # Use existing masters; regenerate game PNGs + SVG enemies
    if [[ -d /tmp/kenney_dl/extracted ]]; then
      exec python3 "$ROOT/tools/import_open_assets.py" --kenney-dir /tmp/kenney_dl/extracted
    fi
    if [[ -d "$ROOT/tools/_kenney_cache" ]]; then
      exec python3 "$ROOT/tools/import_open_assets.py" --kenney-dir "$ROOT/tools/_kenney_cache"
    fi
    exec python3 "$ROOT/tools/import_open_assets.py" --svg-only
  fi
fi

echo "Pillow missing — falling back to shell scale path" >&2
mkdir -p "$ASSETS/tiles" "$ASSETS/sprites/heroes" "$ASSETS/sprites/enemies" "$ASSETS/ui"

scale_nn() {
  local src="$1" dest="$2" size="$3"
  if command -v magick >/dev/null 2>&1; then
    magick "$src" -filter point -resize "${size}x${size}" PNG32:"$dest"
  elif command -v convert >/dev/null 2>&1; then
    convert "$src" -filter point -resize "${size}x${size}" PNG32:"$dest"
  else
    echo "need Pillow or ImageMagick to scale $src" >&2
    return 1
  fi
}

if [[ -f "$KENNEY/field.png" ]]; then
  for name in field wall town water dungeon; do
    [[ -f "$KENNEY/${name}.png" ]] && scale_nn "$KENNEY/${name}.png" "$ASSETS/tiles/${name}.png" 40
  done
  [[ -f "$KENNEY/hero.png" ]] && scale_nn "$KENNEY/hero.png" "$ASSETS/sprites/heroes/hero.png" 40
  [[ -f "$KENNEY/hero.png" ]] && scale_nn "$KENNEY/hero.png" "$ASSETS/sprites/heroes/hero_battle.png" 80
  [[ -f "$KENNEY/hero_other.png" ]] && scale_nn "$KENNEY/hero_other.png" "$ASSETS/sprites/heroes/other.png" 40
  [[ -f "$KENNEY/icon_sword.png" ]] && scale_nn "$KENNEY/icon_sword.png" "$ASSETS/ui/icon_sword.png" 32
  echo "tiles/heroes from kenney masters"
else
  if command -v rsvg-convert >/dev/null 2>&1; then
    for name in field wall town water dungeon; do
      svg="$ASSETS/svg/tile_${name}.svg"
      [[ -f "$svg" ]] && rsvg-convert -w 40 -h 40 "$svg" -o "$ASSETS/tiles/${name}.png"
    done
    [[ -f "$ASSETS/svg/hero.svg" ]] && rsvg-convert -w 40 -h 40 "$ASSETS/svg/hero.svg" -o "$ASSETS/sprites/heroes/hero.png"
    [[ -f "$ASSETS/svg/hero.svg" ]] && rsvg-convert -w 80 -h 80 "$ASSETS/svg/hero.svg" -o "$ASSETS/sprites/heroes/hero_battle.png"
    [[ -f "$ASSETS/svg/hero_other.svg" ]] && rsvg-convert -w 40 -h 40 "$ASSETS/svg/hero_other.svg" -o "$ASSETS/sprites/heroes/other.png"
    echo "tiles/heroes from svg"
  fi
fi

# SVG enemy placeholders
if command -v rsvg-convert >/dev/null 2>&1 && [[ -d "$ASSETS/svg/enemies" ]]; then
  n=0
  for f in "$ASSETS/svg/enemies"/*.svg; do
    [[ -f "$f" ]] || continue
    base=$(basename "$f" .svg)
    rsvg-convert -w 96 -h 96 "$f" -o "$ASSETS/sprites/enemies/${base}.png" && n=$((n + 1)) || true
  done
  echo "enemies from svg: $n"
fi

echo "done → $ASSETS"
echo "tip: python3 tools/import_open_assets.py --download  # refresh Kenney CC0 packs"
