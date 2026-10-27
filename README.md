# Skelly AI Greeter

Make a Home Depot Ultra Skelly talk to trick-or-treaters. When someone presses the
doorbell, camera frames go to Claude, which writes a short, spooky line about the
visitor's costume. The line is spoken in a spooky voice through the Skelly's own speaker.

```
doorbell press -> Home Assistant -> this greeter -> Frigate snapshot -> Claude (vision)
               -> Piper text-to-speech -> sox spooky effect -> Skelly speaker (Bluetooth)
```

A short stalling line ("Hmm... who goes there?") plays immediately, so the AI line
arriving about 3 seconds after the press feels natural.

> **Status:** a hobby project built and tested on one setup (below). Expect to adapt it.
> It sends camera frames of visitors, including children, to a cloud API. Read
> [Privacy and safety](#privacy-and-safety) before you point it at your front door.

## Risk to your Skelly

The bridge this project depends on is provided as-is, at your own risk, and its author
warns it might brick your Skelly. This project adds to that risk, so know exactly what it
does. Over BLE it sends only two commands, both from the bridge's own command set:

1. **Enable classic Bluetooth** (`enable_classic_bt`), once whenever the speaker has to be
   reconnected.
2. **Query volume** (`query_volume`), every 20 seconds, as a keepalive.

It never uploads, deletes or edits stored files, lights, movement, eye icons or settings.
Audio goes over ordinary classic Bluetooth, like any speaker. The 20-second repetition is
this project's own choice, not something the bridge's author tested. In our testing it ran
for hours without trouble, and without it the speaker link dropped within a few minutes.
Raising `KEEPALIVE_SECONDS` makes a dropped speaker link more likely. You use all of this
at your own risk.

## What you need

| Part | Tested with |
| --- | --- |
| Prop | Home Depot 6.5 ft Ultra Skelly (the bridge also lists the 12 ft Skelly and Lethal Lily; not tested here) |
| Computer next to the Skelly | Raspberry Pi 5 (8 GB; 4 GB is plenty), Raspberry Pi OS 64-bit (Debian Trixie) |
| Bluetooth | The Pi's onboard radio worked at about 15 ft. See [docs/SETUP.md](docs/SETUP.md) for dongle notes |
| Skelly bridge | [martinecker/SkellyUltra](https://github.com/martinecker/SkellyUltra) `skelly_ultra_srv` (not included here) |
| Camera | Reolink doorbell, via Frigate 0.18 (any camera Frigate can serve a `latest.jpg` for) |
| Home automation | Home Assistant OS 2026.10 |
| AI | Anthropic API key, model `claude-haiku-5-5` |
| Voice | [Piper](https://pypi.org/project/piper-tts/) (`en_US-ryan-medium`) plus `sox` |

## Quick start

1. Follow [docs/SETUP.md](docs/SETUP.md): install and pair the Skelly bridge, then Piper.
2. Copy `.env.example` to `~/.skelly_env` and fill it in. `chmod 600 ~/.skelly_env`.
3. Run `scripts/install_skelly_services.sh` to install two systemd user services.
4. Add the Home Assistant config from `homeassistant/`.
5. Press the doorbell, then work through [docs/DIALING_IT_IN.md](docs/DIALING_IT_IN.md): the speaker link,
   camera frames, timing, voice and wording all need tuning on your own hardware.
6. Use [docs/HALLOWEEN_NIGHT_CHECKLIST.md](docs/HALLOWEEN_NIGHT_CHECKLIST.md) before the big night.

## Repository layout

```
skelly_greeter.py                       the greeter (aiohttp webhook on port 8766)
.env.example                            every setting, with comments
requirements.txt                        Python packages for the greeter's venv
scripts/install_skelly_services.sh      systemd user services: bridge + greeter
scripts/make_fillers.sh                 render the stalling lines
scripts/voice_options.sh                try voice chains on the real speaker
scripts/ab_blind.sh                      blind A/B test of two voice chains
scripts/ble_keepalive.py                stand-alone BLE keepalive, for debugging
scripts/diff_scan.py                    diff two Bluetooth scan JSON files
homeassistant/                          rest_command, toggle, automations (placeholders)
docs/SETUP.md                           step-by-step build guide, with the gotchas we hit
docs/DIALING_IT_IN.md                   how to make it reliable, fast, clear and well behaved
docs/HALLOWEEN_NIGHT_CHECKLIST.md       the night-of checklist
```

## How it behaves

- **One press, one greeting.** A press during a greeting, or within `COOLDOWN_SECONDS`
  (default 20), is ignored.
- **Groups.** The prompt welcomes a whole group and mentions at most one standout
  costume. It is told never to compare people or guess who is a child or an adult.
- **Self-healing speaker link.** The Skelly drops its Bluetooth speaker when its BLE
  control link goes quiet. The greeter sends a harmless BLE query every 20 seconds, and
  reconnects the speaker if it disappears.
- **Line checker.** Every generated line is screened before it is spoken: ASCII only,
  at most 22 words, and no blocked words or phrases (appearance words, comments about
  what the camera can see or about a missing costume, a few foreign greetings). A rejected line is regenerated
  once, then a canned line is used.

## Privacy and safety

- Each greeting sends **two camera frames, about a second apart, to the Claude API**
  (`SNAPSHOT_COUNT=1` sends one). By default the greeter keeps no copy of them.
  `SAVE_SNAPSHOT=1` saves the latest frames to `/tmp/last_snapshot_1.jpg` and `_2.jpg`
  for debugging; leave it off on the night.
- Frigate's own recordings are separate and are not changed by this project.
- Tell visitors. A small sign saying a camera and AI are in use is the polite minimum,
  and some places have rules about recording children. Check yours.
- The prompt and the line checker reduce the chance of an inappropriate line. They are
  **not a guarantee**. Watch the first greetings, and keep the on/off toggle within reach.
- The code and docs come with no warranty. You are responsible for what your skeleton says.

## Credits and notes

- The Skelly's Bluetooth control comes from
  [martinecker/SkellyUltra](https://github.com/martinecker/SkellyUltra). Clone it
  yourself; this repo does not include or copy its code. The greeter imports its
  `skelly_ultra_pkg.commands` module at runtime to build the BLE frames.
- Built on [Home Assistant](https://www.home-assistant.io/), [Frigate](https://frigate.video/),
  [Piper](https://pypi.org/project/piper-tts/), and the [Anthropic API](https://docs.claude.com/).
- Companion project: [martinecker/SkellyUltraWebController](https://github.com/martinecker/SkellyUltraWebController),
  a browser-based controller for the same props. It can talk to the bridge's REST server as a
  BLE proxy. See "Using the web controller" in [docs/SETUP.md](docs/SETUP.md) before you try.
- **Licensing of the Skelly projects:** when this was written, neither SkellyUltra nor
  SkellyUltraWebController had a license file, only an as-is, at-your-own-risk notice. This
  repo contains none of their code and only tells you to clone them. The greeter's fallback
  contains one eleven-byte device command so it still works without the bridge's Python
  package. If you plan to bundle or fork their code, ask the author first.
- Not affiliated with or endorsed by The Home Depot, the makers of the Ultra Skelly,
  Anthropic, or any project named above. Product names belong to their owners.

## License

MIT, see [LICENSE](LICENSE). Check that the license suits you before publishing.
