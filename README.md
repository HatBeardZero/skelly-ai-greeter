# skelly-ai-greeter

Home Assistant webhook -> Frigate snapshot -> Claude vision -> Piper TTS -> sox spooky
effect -> [SkellyUltra](https://github.com/martinecker/SkellyUltra) `/classic/play`.

Runs on the same machine as `skelly_ultra_srv`. SkellyUltra is a separate upstream
project and is not included here.

## Setup
1. Copy `.env.example` to `~/.skelly_env` and fill it in.
2. Download a Piper voice (e.g. `en_US-ryan-medium`) into `~/voices/` (see `voice_options.sh`).
3. `./install-skelly.sh`
4. Or run directly: `~/greeter-venv/bin/python skelly_greeter.py`
