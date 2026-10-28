#!/bin/sh
# Download 17lands' public Premier Draft datasets (game, draft, replay) of one set outside Git and record checksums.
#   sh scripts/download_17lands.sh [out dir, default ~/mtg-data/17lands/<SET>]     (SET=FDN for Foundations, default DSK)
# Source: https://www.17lands.com/public_datasets (CC BY 4.0). About 900 MB compressed.
set -eu
SET=${SET:-DSK}
OUT=${1:-$HOME/mtg-data/17lands/$SET}
mkdir -p "$OUT" && cd "$OUT"
for k in game_data draft_data replay_data; do
  f=${k}_public.$SET.PremierDraft.csv.gz
  curl -sS -fL --retry 4 -o "$f" "https://17lands-public.s3.amazonaws.com/analysis_data/${k}/${f}"
done
shasum -a 256 *.csv.gz > SHA256SUMS
date -u +"downloaded %Y-%m-%dT%H:%M:%SZ" > DOWNLOADED
cat SHA256SUMS
