#!/usr/bin/env bash
# Download the CS2 category tile icons into both storefronts' public/ folders.
#
# Each icon is one Steam item image at 96x96, drawn by the frontends as a
# silhouette (CSS mask). They are self-hosted because Steam's CDN sends no CORS
# header and a cross-origin mask image does not render. Re-run only to change
# which item stands for a category; the PNGs are committed.
#
# Usage: API=http://localhost:8000 scripts/skins/fetch-category-icons.sh
set -euo pipefail

API="${API:-http://localhost:8000}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIRS=("$ROOT/apps/web/public/skins/categories" "$ROOT/apps/miniapp/public/skins/categories")

# category=slug of the item that stands for it
ICONS=(
  "rifles=ak-47-safari-mesh-minimal-wear"
  "pistols=desert-eagle-night-factory-new"
  "smgs=p90-sand-spray-field-tested"
  "heavy=nova-predator-factory-new"
  "knives=karambit"
  "gloves=sport-gloves-nocts-field-tested"
  "agents=cmdr-mae-dead-cold-jamison-swat"
  "cases=kilowatt-case"
  "keys=gamma-case-key"
  "charms=charm-pocket-awp"
)

for d in "${DIRS[@]}"; do mkdir -p "$d"; done
for pair in "${ICONS[@]}"; do
  category="${pair%%=*}"
  slug="${pair#*=}"
  image="$(curl -fsS "$API/api/v1/skins/$slug" | python3 -c 'import json,sys; print(json.load(sys.stdin)["image_url"])')"
  curl -fsS "${image%/}/96fx96f" -o "${DIRS[0]}/$category.png"
  cp "${DIRS[0]}/$category.png" "${DIRS[1]}/$category.png"
  echo "$category <- $slug"
done
