#!/usr/bin/env python3
"""Skelly greeter v3.

HA webhook -> make sure the Skelly speaker is up -> Frigate snapshot -> Claude vision
-> Piper TTS -> sox spooky effect -> skelly_ultra_srv /classic/play

v3 changes: sends a BLE keepalive every 20s (this kept the Skelly's speaker link
up for 70+ minutes in testing), checks the PipeWire sink directly instead of
trusting the server's status, and keeps the Piper voice loaded in memory.

Run as your normal user on the same machine as skelly_ultra_srv:
  ~/greeter-venv/bin/python skelly_greeter.py
Needs ANTHROPIC_API_KEY, SKELLY_BLE_ADDR, SKELLY_CLASSIC_MAC and FRIGATE_URL in the
environment (see .env.example).
"""
import asyncio
import base64
import collections
import glob
import json
import os
import random
import re
import shlex
import sys
import tempfile
import time
import tomllib
import wave

import aiohttp
import anthropic
from aiohttp import web


def env(key, default):
    return os.getenv(key, default)


def require(key, help_text):
    value = os.getenv(key, "").strip()
    if not value:
        sys.exit(f"Missing required setting {key}: {help_text}\n"
                 "See .env.example and docs/SETUP.md.")
    return value


SKELLY_URL = env("SKELLY_URL", "http://localhost:8765")
BLE_ADDR = require("SKELLY_BLE_ADDR", "the Skelly's BLE address, e.g. AA:BB:CC:DD:EE:FF")
CLASSIC_MAC = require("SKELLY_CLASSIC_MAC", "the Skelly speaker's classic Bluetooth address")
UPLOAD_FIELD = env("UPLOAD_FIELD", "file")

# Build the BLE frames with the repo's own code, same as the keepalive test did
sys.path.insert(0, os.path.expanduser(env("SKELLY_REPO", "~/SkellyUltra/custom_components/skelly_ultra")))
try:
    from skelly_ultra_pkg import commands as skelly_cmds
    ENABLE_FRAME = skelly_cmds.enable_classic_bt().hex()
    KEEPALIVE_FRAME = skelly_cmds.query_volume().hex()
except Exception as e:
    print("Could not import skelly_ultra_pkg, keepalive disabled:", e)
    ENABLE_FRAME = "aafd0100000000000000d1"
    KEEPALIVE_FRAME = None

FRIGATE_URL = require("FRIGATE_URL", "base URL of Frigate, e.g. http://frigate.local:5000")
DEFAULT_CAMERA = env("DEFAULT_CAMERA", "front_door")  # Frigate camera name used when HA sends none
MODEL = env("CLAUDE_MODEL", "claude-haiku-5-5")

PIPER_BIN = os.path.expanduser(env("PIPER_BIN", "~/greeter-venv/bin/piper"))
PIPER_VOICE = os.path.expanduser(env("PIPER_VOICE", "~/voices/en_US-ryan-medium.onnx"))
SOX_EFFECT = env("SOX_EFFECT", "gain -3 pitch -600 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3")  # "" to disable
FILLER_DIR = os.path.expanduser(env("FILLER_DIR", ""))  # optional dir of .wav stalling lines

COOLDOWN = int(env("COOLDOWN_SECONDS", "20"))
SNAPSHOT_DELAY = float(env("SNAPSHOT_DELAY", "1"))
SNAPSHOT_COUNT = max(1, int(env("SNAPSHOT_COUNT", "2")))   # frames sent to Claude per press
SNAPSHOT_GAP = float(env("SNAPSHOT_GAP", "1"))             # seconds between those frames
KEEPALIVE_SECONDS = int(env("KEEPALIVE_SECONDS", "20"))
PORT = int(env("PORT", "8766"))

# Rules every persona shares. The persona file supplies the voice and tone; this
# keeps the visitor-safety rules in one place so a new persona cannot drop them.
COMMON_RULES = (
    "Look at the image(s) and give ONE short spoken line. Hard limit: 15 words in total, sting included, so be brief. "
    "Only mention a costume, mask, hat, or prop that a visitor is wearing or carrying, "
    "if one is clearly visible, and pick "
    "just ONE item, the most obvious one. Never "
    "mention hair, faces, glasses, bodies, age, skin, or weight, and never guess what an outfit is "
    "supposed to be: say 'that hat' or 'that cape', not what it is meant to be. "
    "Never say a costume is confusing, unclear, or a mystery. "
    "If there is no clear costume, just give your usual welcome, and never "
    "comment on a missing costume or on what a visitor is not wearing: a visitor "
    "without a costume is just as welcome. Do not "
    "mention the decorations around the entrance, such as the giant "
    "skeleton, bones, graveyard pieces, or yard figures. "
    "The menace is theatrical and playful, aimed at the night and the gloom, never at "
    "the visitors: never threaten, curse, chase, or hurt a visitor, and no gore, "
    "weapons, or real-world violence. Never claim to know anything personal about a visitor, such as their name "
    "or who they are. Use plain English only: "
    "no foreign words (never say 'amigo' or 'hola'), no accents, and no stereotypes about any culture or "
    "nationality, even if a costume suggests one. If several people are in the "
    "photo, address the whole group (for example, 'what a procession of the brave') and mention "
    "at most one standout costume; never single out, rank, or compare people, and "
    "never guess who is a child or an adult. Never say what you can or "
    "cannot see: no mention of cameras, photos, frames, or whether anyone is visible. "
    "If nobody is in view, just give your usual welcome. "
    "Output only the line, no quotes."
)

OPENING_STYLES = (
    "open with the item or costume itself.",
    "open with a remark about the dark, the cold, or the hour.",
    "open with a span of time, such as years, centuries or a single night.",
    "open with a short one-word reaction that is not 'Ah'.",
    "open with the crypt, the grave, or something underground.",
    "open with a flat, dry statement of fact.",
    "open with a question.",
    "open with the visitors, as a group, arriving.",
)


# ---------- recent lines ----------
# Every accepted line is appended to LINES_FILE (one JSON object per line) and the
# latest few per persona are shown to the model so it stops repeating itself.
LINES_FILE = env("LINES_FILE", os.path.expanduser("~/.skelly_lines.jsonl"))
RECENT_LINES = int(env("RECENT_LINES", "8"))
recent = collections.defaultdict(lambda: collections.deque(maxlen=RECENT_LINES))


def load_recent():
    try:
        with open(LINES_FILE) as fh:
            for row in fh.readlines()[-400:]:
                try:
                    r = json.loads(row)
                    recent[r["persona"]].append(r["line"])
                except (ValueError, KeyError):
                    continue
    except OSError:
        pass


def remember(persona, line, spoken):
    recent[persona].append(line)
    try:
        with open(LINES_FILE, "a") as fh:
            fh.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                 "persona": persona, "spoken": spoken, "line": line}) + "\n")
    except OSError as e:
        print("Could not log line:", e)


# ---------- personas ----------
# Each file in personas/ is a voice: a `tone` prompt and canned `fallbacks`.
# Pick one with PERSONA in ~/.skelly_env (hard setting), or per doorbell press by
# sending {"persona": "exhibition"} from Home Assistant (routing rule).
PERSONA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "personas")
DEFAULT_PERSONA = env("PERSONA", "crypt")
_personas = {}
# Comparison aid: these personas also write a line from the same frames, which is
# only logged, never spoken. Off by default; e.g. SHADOW_PERSONAS=exhibition
SHADOW_PERSONAS = [n.strip() for n in env("SHADOW_PERSONAS", "").split(",") if n.strip()]


def get_persona(name=None):
    """Return {'system': ..., 'fallbacks': [...], 'name': ...}; unknown names use the default."""
    for candidate in (name, DEFAULT_PERSONA, "crypt"):
        if not candidate or not re.fullmatch(r"[a-z0-9_-]+", str(candidate)):
            continue
        if candidate in _personas:
            return _personas[candidate]
        path = os.path.join(PERSONA_DIR, f"{candidate}.toml")
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
            fallbacks = [str(x) for x in data.get("fallbacks", [])] or [
                "Who dares approach... come closer."]
            _personas[candidate] = {
                "name": candidate,
                "system": " ".join(data["tone"].split()) + " " + COMMON_RULES,
                "fallbacks": fallbacks,
                "filter": bool(data.get("filter", True)),
                "pun_chance": float(data.get("pun_chance", 0)),
            }
            if name and candidate != name:
                print(f"Persona {name!r} not found, using {candidate!r}")
            return _personas[candidate]
        except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
            print(f"Could not load persona {candidate!r}: {e}")
    raise RuntimeError("no usable persona in " + PERSONA_DIR)


client = anthropic.AsyncAnthropic()
lock = asyncio.Lock()
last_run = 0.0
ble_session = None
voice = None


# ---------- Skelly server helpers ----------

async def srv(session, method, path, **kw):
    try:
        async with session.request(
            method, SKELLY_URL + path,
            timeout=aiohttp.ClientTimeout(total=20), **kw
        ) as r:
            return await r.json(content_type=None)
    except Exception as e:
        print(f"{path} failed: {e}")
        return {}


async def sink_present():
    """The real test: does PipeWire have the Skelly's speaker sink?"""
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "sinks", "short",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return CLASSIC_MAC.replace(":", "_").upper() in out.decode(errors="ignore").upper()


async def ble_send(session, frame):
    body = {"command": frame}
    if ble_session:
        body["session_id"] = ble_session
    r = await srv(session, "POST", "/ble/send_command", json=body)
    return bool(r.get("success"))


async def ble_connect(session):
    global ble_session
    conn = await srv(session, "POST", "/ble/connect", json={"address": BLE_ADDR})
    ble_session = conn.get("session_id")
    return bool(ble_session)


async def _ensure_connected(session, tries=3):
    for i in range(tries):
        if await sink_present():
            return True
        print(f"Skelly speaker not present, reconnecting (try {i + 1})")
        if not await ble_send(session, ENABLE_FRAME):
            await ble_connect(session)
            await ble_send(session, ENABLE_FRAME)
        await asyncio.sleep(3)
        await srv(session, "POST", "/classic/connect_by_mac", json={"mac": CLASSIC_MAC})
        await asyncio.sleep(2)
    return await sink_present()


reconnect_lock = asyncio.Lock()


async def ensure_connected(session, tries=3):
    # A second caller waits here, then sees the sink is already up
    async with reconnect_lock:
        return await _ensure_connected(session, tries)


async def play(session, path):
    form = aiohttp.FormData()
    with open(path, "rb") as fh:
        form.add_field(UPLOAD_FIELD, fh, filename=os.path.basename(path),
                       content_type="audio/wav")
        async with session.post(f"{SKELLY_URL}/classic/play", data=form) as r:
            r.raise_for_status()


def wav_seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


# ---------- AI + audio pipeline ----------

async def snapshot(session, camera, index=0):
    url = f"{FRIGATE_URL}/api/{camera}/latest.jpg?h=720"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
        r.raise_for_status()
        data = await r.read()
    # Debug: keep the most recent frames so you can see what Claude was shown.
    # Off by default so no frames are kept. Set SAVE_SNAPSHOT=1 to keep them at
    # /tmp/last_snapshot_1.jpg, /tmp/last_snapshot_2.jpg, ... while debugging.
    if env("SAVE_SNAPSHOT", "0") == "1":
        try:
            with open(f"/tmp/last_snapshot_{index + 1}.jpg", "wb") as fh:
                fh.write(data)
        except OSError:
            pass
    return data


async def snapshots(session, camera):
    """Grab SNAPSHOT_COUNT frames SNAPSHOT_GAP seconds apart. Catches people who were
    looking away or mid-stride in the first frame. If a later frame fails, the frames
    already captured are used; if the first fails, the error propagates (fallback line)."""
    frames = [await snapshot(session, camera, 0)]
    for i in range(1, SNAPSHOT_COUNT):
        await asyncio.sleep(SNAPSHOT_GAP)
        try:
            frames.append(await snapshot(session, camera, i))
        except Exception as e:
            print(f"Extra snapshot {i + 1} failed, continuing with {len(frames)}:", e)
            break
    return frames


async def make_line(jpgs, persona):
    images = [
        {"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.b64encode(j).decode()}}
        for j in jpgs
    ]
    if len(images) > 1:
        prompt = ("These frames are from the same doorbell press, about a second apart. "
                  "Use whichever frame shows the visitors best. Greet them.")
    else:
        prompt = "Greet them."
    # A random structural nudge each press, so lines stop sharing the same opening.
    prompt += "\n\nFor this line, " + random.choice(OPENING_STYLES) + " Do not open with 'Ah'."
    if random.random() < persona["pun_chance"]:
        prompt += ("\n\nThis time, make the line a skeleton pun on bones, ribs, skulls, "
                   "having no body or no heart, in the spirit of a cheerful skeleton "
                   "who cannot help himself, delivered with a straight face.")
    used = list(recent[persona["name"]])
    if used:
        prompt += ("\n\nLines you already used recently. Do not repeat their wording, "
                   "openings, jokes or sentence shape; find a fresh angle:\n"
                   + "\n".join(f"- {u}" for u in used))
    params = dict(
        model=MODEL,
        max_tokens=300,  # headroom in case the model emits a thinking block first
        system=persona["system"],
        messages=[{
            "role": "user",
            "content": images + [{"type": "text", "text": prompt}],
        }],
    )
    # Thinking only adds latency for a one-line greeting. Haiku 5.5 allows
    # thinking disabled at high effort or below (its default effort is medium).
    extra = {"thinking": {"type": env("THINKING_MODE", "disabled")}}  # Sonnet 5.5 wants between_tools
    effort = env("CLAUDE_EFFORT", "")  # optional: low | medium | high
    if effort:
        extra["output_config"] = {"effort": effort}
    try:
        resp = await client.messages.create(**params, **extra)
    except (TypeError, anthropic.BadRequestError) as e:
        print("thinking/effort settings rejected, retrying with defaults (slower):", e)
        resp = await client.messages.create(**params)
    # The reply can start with a thinking block, so collect only the text blocks
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    if not text:
        raise RuntimeError("no text block in the response")
    return text


def load_voice():
    """Keep the Piper model in memory so each greeting skips the load time."""
    global voice
    try:
        from piper import PiperVoice
        voice = PiperVoice.load(PIPER_VOICE)
        print("Piper voice loaded in-process")
    except Exception as e:
        print("In-process Piper unavailable, will use the CLI:", e)


def synth_sync(text, path):
    with wave.open(path, "wb") as wf:
        voice.synthesize_wav(text, wf)


async def tts(text, path):
    if voice is not None:
        try:
            await asyncio.to_thread(synth_sync, text, path)
            return
        except Exception as e:
            print("In-process TTS failed, using the CLI:", e)
    proc = await asyncio.create_subprocess_exec(
        PIPER_BIN, "-m", PIPER_VOICE, "-f", path,
        stdin=asyncio.subprocess.PIPE,
    )
    await proc.communicate(text.encode())
    if proc.returncode != 0:
        raise RuntimeError("piper failed")


async def spookify(src, dst):
    if not SOX_EFFECT:
        return src
    proc = await asyncio.create_subprocess_exec("sox", src, dst, *shlex.split(SOX_EFFECT))
    await proc.wait()
    return dst if proc.returncode == 0 else src


# ---------- safety net for the generated line ----------

# Prompt rules aren't a guarantee, so the code double-checks every line before
# it is spoken. A rejected line is regenerated once, then a canned line is used.
BANNED_WORDS = {
    # appearance
    "hair", "glasses", "spectacles", "face", "faces", "fat", "skinny", "ugly", "weird",
    # talking about what it can or can't see (sounds like it's watching)
    "visible", "invisible", "camera", "photo", "frame", "frames", "nobody",
    # spooky is fine, but keep the menace off the visitors
    "kill", "killed", "murder", "suicide", "stab", "gun", "shoot",
    # foreign-language filler the model likes to add for certain costumes
    "amigo", "amiga", "amigos", "senor", "senorita", "hola", "ole", "gracias",
    "compadre", "muchacho", "muchacha", "bonjour", "ciao",
}

# Whole phrases the word list cannot express.
BANNED_PHRASES = ("no costume", "not a single", "without a costume", "no disguise",
                  "no one", "in sight", "out of sight",
                  # sounding like it is watching the visitor (plain "seen"/"see" are fine)
                  "i see ", "i can see", "i could see", "can see you", "see you standing",
                  "see you there", "i have seen you", "i've seen you", "watching you",
                  "watched you", "watching from", "been watching")


def line_ok(line, persona=None):
    if persona is not None and not persona.get("filter", True):
        # Persona opted out of the word checks: only reject empty or run-on lines.
        return 0 < len(line.split()) <= 40
    text = line.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    if not text.isascii():  # accents mean foreign words (senor, ole, etc.)
        return False
    words = re.findall(r"[a-z']+", text.lower())
    if not words or len(words) > 22:
        return False
    lowered = text.lower()
    if any(p in lowered for p in BANNED_PHRASES):
        return False
    return not any(w in BANNED_WORDS for w in words)


# ---------- main flow ----------

async def shadow_line(frames, name):
    try:
        p = get_persona(name)
        line = await make_line(frames, p)
        if line_ok(line, p):
            remember(p["name"], line, False)
        print(f"Shadow ({p['name']}, not spoken, {'ok' if line_ok(line, p) else 'would be rejected'}):", line)
    except Exception as e:
        print(f"Shadow persona {name!r} failed:", e)


async def run(camera, persona_name=None):
    persona = get_persona(persona_name)
    async with lock:
        t0 = time.time()
        async with aiohttp.ClientSession() as session:
            try:
                if not await ensure_connected(session):
                    print("Could not bring the Skelly speaker up, skipping this greeting")
                    return

                # Stall with a canned line while the AI chain runs
                filler_end = t0
                fillers = glob.glob(os.path.join(FILLER_DIR, "*.wav")) if FILLER_DIR else []
                if fillers:
                    f = random.choice(fillers)
                    await play(session, f)
                    filler_end = t0 + wav_seconds(f)
                    print(f"[timing] filler {os.path.basename(f)} started {time.time() - t0:.1f}s, lasts {wav_seconds(f):.1f}s")

                await asyncio.sleep(max(0, SNAPSHOT_DELAY - (time.time() - t0)))
                line = None
                frames = None
                for attempt in range(3):
                    try:
                        # Capture once; a retry reuses the same frames (no extra delay)
                        if frames is None:
                            frames = await snapshots(session, camera)
                            print(f"[timing] {len(frames)} frame(s) captured {time.time() - t0:.1f}s")
                        if attempt == 0:
                            for name in SHADOW_PERSONAS:
                                if name != persona["name"]:
                                    asyncio.create_task(shadow_line(frames, name))
                        candidate = await make_line(frames, persona)
                    except Exception as e:
                        print("AI step failed, using fallback:", e)
                        break
                    if line_ok(candidate, persona):
                        line = candidate
                        break
                    print("Rejected line, trying again:" if attempt < 2 else "Rejected line:", candidate)
                if line is None:
                    line = random.choice(persona["fallbacks"])
                else:
                    remember(persona["name"], line, True)
                print(f"Skelly says ({persona['name']}):", line)
                print(f"[timing] line ready {time.time() - t0:.1f}s after trigger")

                with tempfile.TemporaryDirectory() as tmp:
                    raw = os.path.join(tmp, "raw.wav")
                    await tts(line, raw)
                    print(f"[timing] voice synthesized {time.time() - t0:.1f}s")
                    out = await spookify(raw, os.path.join(tmp, "spooky.wav"))
                    print(f"[timing] effect applied {time.time() - t0:.1f}s")
                    await asyncio.sleep(max(0, filler_end - time.time()))
                    await play(session, out)
                    print(f"[timing] audio sent to Skelly {time.time() - t0:.1f}s")
                    await asyncio.sleep(wav_seconds(out))  # hold the lock until done
            except Exception as e:
                print("greet failed:", e)


# Optional: POSTed when the greeter is ready to greet again (speech done and cooldown
# over), so Home Assistant can undo a "recharging" light change. Leave unset to disable.
READY_WEBHOOK_URL = env("READY_WEBHOOK_URL", "")


def is_ready():
    return not lock.locked() and time.time() - last_run >= COOLDOWN


async def notify_ready():
    if not READY_WEBHOOK_URL:
        return
    await asyncio.sleep(max(0, last_run + COOLDOWN - time.time()))
    if not is_ready():  # a newer press is running; its own run will notify
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(READY_WEBHOOK_URL, json={"ready": True},
                                    timeout=aiohttp.ClientTimeout(total=5)) as r:
                print(f"[ready] webhook -> {r.status}")
    except Exception as e:
        print("Ready webhook failed:", e)


async def run_then_notify(camera, persona_name):
    try:
        await run(camera, persona_name)
    finally:
        await notify_ready()


async def status(request):
    return web.json_response({"ready": is_ready()})


async def greet(request):
    global last_run
    try:
        data = await request.json()
    except Exception:
        data = {}
    if lock.locked() or time.time() - last_run < COOLDOWN:
        return web.json_response({"status": "skipped"})
    last_run = time.time()
    asyncio.create_task(run_then_notify(data.get("camera", DEFAULT_CAMERA), data.get("persona")))
    return web.json_response({"status": "ok"})


async def keepalive(app):
    """Keep the BLE link busy (keeps the speaker link up) and heal drops while idle."""
    async def loop():
        while True:
            try:
                async with aiohttp.ClientSession() as s:
                    if await sink_present():
                        if KEEPALIVE_FRAME and not await ble_send(s, KEEPALIVE_FRAME):
                            await ble_connect(s)
                    elif not lock.locked():
                        await ensure_connected(s, tries=1)
            except Exception as e:
                print("keepalive error:", e)
            await asyncio.sleep(KEEPALIVE_SECONDS)

    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = web.Application()
app.add_routes([web.post("/greet", greet), web.get("/status", status)])
app.cleanup_ctx.append(keepalive)

if __name__ == "__main__":
    load_recent()
    load_voice()
    web.run_app(app, port=PORT)
