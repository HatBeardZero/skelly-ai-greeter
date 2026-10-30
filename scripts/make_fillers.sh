#!/usr/bin/env bash
# Renders short stalling lines that play instantly while the AI line is being made.
# Usage: bash scripts/make_fillers.sh   (then set FILLER_DIR=~/fillers in ~/.skelly_env)
set -euo pipefail
VOICE="${PIPER_VOICE:-$HOME/voices/en_US-ryan-medium.onnx}"
PIPER="${PIPER_BIN:-$HOME/greeter-venv/bin/piper}"
EFFECT="${SOX_EFFECT:-gain -3 pitch -450 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3}"
OUT="${FILLER_DIR:-$HOME/fillers}"
mkdir -p "$OUT"
i=0
for t in "Hmm... who goes there... who dares disturb my rest?" "Ah... visitors. It has been so long... so very long." "Come closer, if you dare... closer still." "Who disturbs my rest... in the dead of night?"; do
  i=$((i + 1))
  echo "$t" | "$PIPER" -m "$VOICE" -f /tmp/filler_raw.wav
  # shellcheck disable=SC2086
  sox /tmp/filler_raw.wav "$OUT/filler_$i.wav" $EFFECT
done
rm -f /tmp/filler_raw.wav
ls -l "$OUT"
