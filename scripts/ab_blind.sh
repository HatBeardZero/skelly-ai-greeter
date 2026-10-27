#!/usr/bin/env bash
# Blind A/B voice test through the Skelly's speaker.
#
# For each test line it renders the line two ways, plays them in RANDOM order
# (you don't know which is which), asks which one you preferred, and tallies the
# result at the end. Needs the Skelly bridge running with the speaker connected
# (the greeter service keeps it connected), plus Piper and sox.
#
# Usage:  bash ab_blind.sh
# Edit CHAIN_A / CHAIN_B below to compare any two effect chains.
set -u

# Both chains end with the same level normalisation, so loudness can't decide it.
CHAIN_A="gain -3 pitch -600 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3"
CHAIN_B="gain -3 pitch -600 bass 8 250 treble -6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3"

PIPER="${PIPER_BIN:-$HOME/greeter-venv/bin/piper}"
VOICE="${PIPER_VOICE:-$HOME/voices/en_US-ryan-medium.onnx}"
SERVER="${SKELLY_URL:-http://localhost:8765}"
# How a clip is played. Override PLAY_CMD for testing without a Skelly.
play_file() { curl -s -X POST "$SERVER/classic/play" -F "file=@$1" > /dev/null; }
[ -n "${PLAY_CMD:-}" ] && play_file() { $PLAY_CMD "$1"; }

LINES=(
  "Who dares knock upon my crypt... splendid cape. Take your candy and linger not."
  "Another year of waiting in the dark... and here you are. Marvelous hat."
  "Ah... a brave procession. My bones rattle with approval."
)

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
winsA=0
winsB=0
n=0

for text in "${LINES[@]}"; do
  n=$((n + 1))
  echo "$text" | "$PIPER" -m "$VOICE" -f "$WORK/raw$n.wav" 2>/dev/null
  # shellcheck disable=SC2086
  sox "$WORK/raw$n.wav" "$WORK/A$n.wav" $CHAIN_A 2>/dev/null
  # shellcheck disable=SC2086
  sox "$WORK/raw$n.wav" "$WORK/B$n.wav" $CHAIN_B 2>/dev/null

  # random order: first = A or B
  if [ $((RANDOM % 2)) -eq 0 ]; then first=A; second=B; else first=B; second=A; fi

  for slot in 1 2; do
    if [ "$slot" -eq 1 ]; then which=$first; else which=$second; fi
    echo "Round $n, clip $slot..."
    play_file "$WORK/$which$n.wav"
    dur=$(soxi -D "$WORK/$which$n.wav" 2>/dev/null || echo 8)
    sleep "$(awk -v d="$dur" 'BEGIN { printf "%.1f", d + 2.5 }')"
  done

  pick=""
  while [ "$pick" != "1" ] && [ "$pick" != "2" ]; do
    read -r -n1 -p "Round $n: which sounded better, 1 or 2? " pick
    echo
  done
  if [ "$pick" = "1" ]; then chosen=$first; else chosen=$second; fi
  if [ "$chosen" = "A" ]; then winsA=$((winsA + 1)); else winsB=$((winsB + 1)); fi
done

echo
echo "Result:  A = $winsA   B = $winsB"
echo "A: $CHAIN_A"
echo "B: $CHAIN_B"
