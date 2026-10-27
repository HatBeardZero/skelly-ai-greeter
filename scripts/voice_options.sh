#!/usr/bin/env bash
# Plays one line through several voice chains, one after another, labelled in the
# terminal, so you can pick the deepest / most gravelly sound on the Skelly's speaker.
#
# Needs the Skelly bridge running with the speaker connected (the greeter service
# keeps it connected), plus Piper and sox.
#
# Usage:   bash voice_options.sh
# Replay one option:   bash voice_options.sh 2
# Milder second round:   SET=2 bash voice_options.sh
# Clarity round:   SET=3 bash voice_options.sh   (use a real greeting: TEXT="..." SET=3 bash voice_options.sh)
set -u

PIPER="${PIPER_BIN:-$HOME/greeter-venv/bin/piper}"
VOICE="${PIPER_VOICE:-$HOME/voices/en_US-ryan-medium.onnx}"
SERVER="${SKELLY_URL:-http://localhost:8765}"
TEXT="${TEXT:-Who dares knock upon my crypt... splendid cape. Take your candy and linger not.}"

play_file() { curl -s -X POST "$SERVER/classic/play" -F "file=@$1" > /dev/null; }
[ -n "${PLAY_CMD:-}" ] && play_file() { $PLAY_CMD "$1"; }

# label | sox effect chain. Every chain ends with norm -3 so loudness is comparable.
# SET=1 (default): the wide first round. SET=2: milder options between "ok" and "too harsh".
# SET=4: pitch ladder (-800 down to -300) with the same clarity treatment on each.
# SET=3: clarity round (less reverb, presence boost) for when the words are hard to understand.
SET="${SET:-1}"
if [ "$SET" = "3" ]; then
  # Clarity round: the deep voice is hard to understand, so trade reverb/grit for words.
  NAMES=(
    "0  current (-800, reverb 50): the reference that was hard to understand"
    "1  same voice, much less reverb"
    "2  less reverb, lighter overdrive, no tremolo"
    "3  -800, less reverb, plus a presence boost (2.5 kHz) for consonants"
    "4  -600, less reverb, plus the presence boost"
  )
  CHAINS=(
    "gain -3 pitch -800 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3"
    "gain -3 pitch -800 bass 6 overdrive 6 tremolo 7 30 reverb 20 40 50 norm -3"
    "gain -3 pitch -800 bass 6 overdrive 4 reverb 20 40 50 norm -3"
    "gain -3 pitch -800 bass 6 overdrive 6 tremolo 7 30 equalizer 2500 1q 6 reverb 20 40 50 norm -3"
    "gain -3 pitch -600 bass 6 overdrive 6 tremolo 7 30 equalizer 2500 1q 6 reverb 20 40 50 norm -3"
  )
elif [ "$SET" = "4" ]; then
  # Pitch ladder: identical clarity treatment on every option, ONLY the pitch changes.
  NAMES=(
    "0  pitch -800 (the deep one that was hard to understand)"
    "1  pitch -600"
    "2  pitch -500"
    "3  pitch -400"
    "4  pitch -300 (what the greeter used for most of today's tests)"
  )
  CHAINS=(
    "gain -3 pitch -800 bass 6 overdrive 6 tremolo 7 30 equalizer 2500 1q 6 reverb 20 40 50 norm -3"
    "gain -3 pitch -600 bass 6 overdrive 6 tremolo 7 30 equalizer 2500 1q 6 reverb 20 40 50 norm -3"
    "gain -3 pitch -500 bass 6 overdrive 6 tremolo 7 30 equalizer 2500 1q 6 reverb 20 40 50 norm -3"
    "gain -3 pitch -400 bass 6 overdrive 6 tremolo 7 30 equalizer 2500 1q 6 reverb 20 40 50 norm -3"
    "gain -3 pitch -300 bass 6 overdrive 6 tremolo 7 30 equalizer 2500 1q 6 reverb 20 40 50 norm -3"
  )
elif [ "$SET" = "2" ]; then
  NAMES=(
    "0  baseline: -800, light grit (the one that was ok)"
    "1  -800, a bit more grit (overdrive 9)"
    "2  -900, same light grit as the baseline"
    "3  -800, more grit and a slow 20 Hz growl"
    "4  -800, more grit, no tremolo (jaw-safe)"
  )
  CHAINS=(
    "gain -3 pitch -800 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3"
    "gain -3 pitch -800 bass 6 overdrive 9 tremolo 7 30 reverb 50 50 80 norm -3"
    "gain -3 pitch -900 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3"
    "gain -3 pitch -800 bass 6 overdrive 9 tremolo 20 40 reverb 50 50 80 norm -3"
    "gain -3 pitch -800 bass 6 overdrive 9 reverb 50 50 80 norm -3"
  )
else
  NAMES=(
    "0  current (-600, light grit)"
    "1  deeper only (-800)"
    "2  gravelly (-700, heavy overdrive, fast tremolo growl)"
    "3  very gravelly (-800, heavier overdrive and growl)"
    "4  gravel without tremolo (jaw-safe: -700, heavy overdrive)"
  )
  CHAINS=(
    "gain -3 pitch -600 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3"
    "gain -3 pitch -800 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3"
    "gain -3 pitch -700 bass 6 overdrive 15 tremolo 40 50 reverb 40 50 80 norm -3"
    "gain -6 pitch -800 bass 8 overdrive 20 15 tremolo 55 60 reverb 40 50 80 norm -3"
    "gain -3 pitch -700 bass 6 overdrive 18 reverb 40 50 80 norm -3"
  )
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "$TEXT" | "$PIPER" -m "$VOICE" -f "$WORK/raw.wav" 2>/dev/null || { echo "Piper failed"; exit 1; }

play_one() {
  local i="$1"
  # shellcheck disable=SC2086
  sox "$WORK/raw.wav" "$WORK/o$i.wav" ${CHAINS[$i]} 2> "$WORK/err$i.txt"
  echo "Playing option ${NAMES[$i]}"
  grep -i "clipped" "$WORK/err$i.txt" | sed 's/^/   (note) /'
  play_file "$WORK/o$i.wav"
  local dur
  dur=$(soxi -D "$WORK/o$i.wav" 2>/dev/null || echo 8)
  sleep "$(awk -v d="$dur" 'BEGIN { printf "%.1f", d + 3 }')"
}

if [ $# -ge 1 ]; then
  play_one "$1"
else
  for i in "${!CHAINS[@]}"; do play_one "$i"; done
fi

echo
echo "To use an option, put its chain in ~/.skelly_env as SOX_EFFECT=\"...\" (quoted):"
for i in "${!CHAINS[@]}"; do echo "  ${NAMES[$i]}"; echo "     ${CHAINS[$i]}"; done
