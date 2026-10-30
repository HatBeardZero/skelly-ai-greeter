# Setup guide

Everything here was done on a Raspberry Pi 5 running Raspberry Pi OS 64-bit (Debian
Trixie), with Home Assistant OS and Frigate on other machines. Adapt as needed.

## 1. Prepare the Pi

1. Flash Raspberry Pi OS (64-bit) with Raspberry Pi Imager. In its settings screen, set a
   hostname, a user, enable SSH and add Wi-Fi if you are not using Ethernet.
2. Put the Pi on the **same network as Home Assistant and Frigate**, not a guest network
   (guest networks usually isolate devices from each other).
3. Give it a DHCP reservation in your router.
4. Update, then reboot: `sudo apt update && sudo apt full-upgrade -y`.
5. Check power and audio: `vcgencmd get_throttled` should print `0x0`, and
   `pw-play --version` should print a version. A weak power supply causes odd USB and
   Bluetooth problems; use a proper 5 V / 5 A supply on a Pi 5.

## 2. Bluetooth adapter

The Skelly bridge's README says the Pi's built-in Bluetooth often streams audio
choppily and recommends a dedicated USB dongle (the author used a TP-Link UB500 Plus).

Our experience: the onboard radio gave good audio at about 15 ft, so we kept it. An ASUS
USB-BT600 was detected (`lsusb`) but never initialised on Raspberry Pi OS with kernel
6.18 (the log repeated `RTL: Read reg16 failed (-110)`), so we returned it. Check
`dmesg | grep -i bluetooth` after plugging a dongle in; if it loops like that, try a
different model. Test audio at the **final distance**, not on your desk.

## 3. Install the Skelly bridge (not part of this repo)

```
cd ~
git clone https://github.com/martinecker/SkellyUltra.git
sudo apt install -y pulseaudio-utils python3-aiohttp python3-dbus-next python3-bleak
cd ~/SkellyUltra/custom_components/skelly_ultra/skelly_ultra_srv
python3 run_server.py
```

Follow that project's own README for details. The packages above come from apt because
Debian Trixie blocks plain `pip install` into the system Python. In a second terminal,
`curl localhost:8765/health` should return `{"status": "ok"}`.

## 4. Find the Skelly's addresses

The Skelly has **two** Bluetooth identities: a BLE control address and a classic speaker
address. The bridge's README gives the names:

| Firmware | BLE name | Classic speaker name |
| --- | --- | --- |
| Older Ultra Skelly | `Animated Skelly` | `Animated Skelly(Live)` |
| Current Ultra Skelly | `Ultra Skelly v2` | `Ultra Skelly v2(Live)` |

Our Skelly used the older names. Look for whichever pair yours advertises.

1. Close the Skelly phone app completely. It holds the Skelly's single BLE connection.
2. Power the Skelly on, within a few feet of the Pi, and run
   `curl -s localhost:8765/ble/scan_devices`. Look for the `Animated Skelly` (or
   `Ultra Skelly v2`) entry. That is `SKELLY_BLE_ADDR`.
3. The speaker only shows up after a BLE command turns "classic" mode on. Connect and send
   it (the frame is built by the bridge's own code):
   ```
   cd ~/SkellyUltra/custom_components/skelly_ultra
   python3 -c "from skelly_ultra_pkg import commands; print(commands.enable_classic_bt().hex())"
   curl -X POST localhost:8765/ble/connect -H "Content-Type: application/json" \
        -d '{"address": "<SKELLY_BLE_ADDR>"}'
   curl -X POST localhost:8765/ble/send_command -H "Content-Type: application/json" \
        -d '{"command": "<hex printed above>"}'
   bluetoothctl --timeout 20 scan on
   bluetoothctl devices
   ```
   The new device with `(Live)` after its name is the speaker: that is `SKELLY_CLASSIC_MAC`.
4. Pair it once (the bridge's README gives `1234` as the default PIN, and it worked for us):
   ```
   curl -X POST localhost:8765/classic/pair_and_trust_by_mac \
        -H "Content-Type: application/json" \
        -d '{"mac": "<SKELLY_CLASSIC_MAC>", "pin": "1234"}'
   ```
   Pairing needs sudo. It failed with "Sudo requires password" for us, and worked after
   entering the sudo password in a root shell (`sudo su`) and calling the endpoint from
   there. The bridge's README also documents a sudoers rule and a manual `bluetoothctl`
   method. Pairing is one-time.
5. Connect and test:
   ```
   curl -X POST localhost:8765/classic/connect_by_mac -H "Content-Type: application/json" \
        -d '{"mac": "<SKELLY_CLASSIC_MAC>"}'
   espeak-ng -w /tmp/t.wav "Testing one two three"   # sudo apt install espeak-ng
   curl -X POST localhost:8765/classic/play -F "file=@/tmp/t.wav"
   ```

**Gotchas we hit**

- **Silence even though the API says "playing":** the Skelly's physical **mode button must
  be on Bluetooth**, and the volume knob up. If the speaker link is down, PipeWire plays
  into a dummy `auto_null` sink and the server still reports success.
- **The speaker link dies on its own every few minutes** unless something keeps the BLE
  link busy. The greeter handles this with a keepalive (see "How it behaves" in the README).
- Whether streamed audio moves the jaw: it did on our Skelly.

## 5. Voice: Piper and sox

```
sudo apt install -y sox
python3 -m venv --system-site-packages ~/greeter-venv
~/greeter-venv/bin/pip install -r requirements.txt
mkdir -p ~/voices && cd ~/voices
~/greeter-venv/bin/python -m piper.download_voices en_US-ryan-medium
```

Test the voice and the spooky effect through the Skelly:

```
echo "Welcome, brave souls." | ~/greeter-venv/bin/piper -m ~/voices/en_US-ryan-medium.onnx -f /tmp/p.wav
sox /tmp/p.wav /tmp/p2.wav gain -3 pitch -450 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3
curl -X POST localhost:8765/classic/play -F "file=@/tmp/p2.wav"
```

The default chain is `gain -3 pitch -450 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3`.
What we learned tuning it on the Skelly's small speaker (judge by ear, on the speaker, not
on a laptop):

- **Pitch:** `pitch` is in cents. -450 sounded best on the Skelly outdoors. -600 was also clear.
  -800 sounded deeper on a laptop but was hard to understand on the Skelly.
- **Heavy overdrive and a fast tremolo growl** (overdrive 15 or more, tremolo 40 Hz or
  more) sounded bad and clipped. Keep the grit light.
- **`norm -3` at the end** keeps the level up. Without it, the tremolo plus reverb made the
  output about 13 dB quieter in our measurements.
- If the jaw looks twitchy, drop `tremolo 7 30` first. If it clips, change `gain -3` to
  `gain -6`.
- If the words are muddy, cut the reverb (for example `reverb 20 40 50`) or add a presence
  boost such as `equalizer 2500 1q 6` just before the reverb.

`scripts/voice_options.sh` plays one line through several chains in a row on the real
speaker (`SET=1` to `SET=4` pick different rounds, and `TEXT="..."` sets the line). Always
test with a full-length greeting, not a short test phrase.

Stalling lines: `scripts/make_fillers.sh` renders a few into `~/fillers`.

## 6. Frigate

The greeter fetches `FRIGATE_URL/api/<camera>/latest.jpg?h=720`. Check it works from the
Pi: `curl -o /tmp/snap.jpg "http://<frigate>:5000/api/<camera>/latest.jpg?h=720"`, then
look at the image. It must be big enough to read a costume (ours was 960x720). If your
camera's detect stream is tiny, raise the detect resolution or use another frame source.

## 7. The greeter

1. `cp .env.example ~/.skelly_env`, fill it in, `chmod 600 ~/.skelly_env`. Put any value
   with spaces (such as `SOX_EFFECT`) in double quotes. Without quotes, systemd reads it
   fine but `source ~/.skelly_env` in a shell breaks on it (`bash: -3: command not found`)
   and leaves the variable empty, so sox then runs with no effects at all.
2. API access is billed separately from a Claude.ai subscription. Create a key in the
   Anthropic Console, add a few dollars of credit, and set a spend limit.
3. Test by hand:
   ```
   set -a; source ~/.skelly_env; set +a
   ~/greeter-venv/bin/python skelly_greeter.py
   curl -X POST localhost:8766/greet -H "Content-Type: application/json" -d '{"camera": "front_door"}'
   ```
   The log prints `[timing]` lines and `Skelly says: ...`. Stand in frame first: the frame
   is taken about a second after the trigger.
4. Copy the greeter to your home folder (`cp skelly_greeter.py ~/`; or set `GREETER_PATH`
   when running the installer), then install the services:
   `bash scripts/install_skelly_services.sh`. Then
   `systemctl --user start skelly-server skelly-greeter`. Logs:
   `journalctl --user-unit skelly-greeter -f`.
5. Reboot once and check the Skelly's sink comes back without you touching anything:
   `pactl list sinks short | grep -i <SKELLY_CLASSIC_MAC with : replaced by _>`.

Notes on the Claude call: Haiku 5.5 can start a reply with a thinking block, so the code
reads only text blocks, and it turns thinking off for latency. If you change the model,
re-check both.

## 8. Home Assistant

1. Create a **Toggle** helper named `Skelly greeter` (Settings, Devices & services,
   Helpers). Its entity is `input_boolean.skelly_greeter`.
2. Add the `rest_command` from `homeassistant/configuration.example.yaml` to
   `configuration.yaml`, check the configuration, and restart.
3. Create the automations from `homeassistant/automations.example.yaml`.
4. Test from Settings, Tools, Actions: run `rest_command.skelly_greet` with
   `camera: <your Frigate camera>`.

The Skelly speaks only when the toggle is **on** and the time condition passes.

## 9. Timing we measured

With `SNAPSHOT_DELAY=0.5` and `SNAPSHOT_GAP=0.5` on a fast camera feed:

| Stage | Time after the press |
| --- | --- |
| Stalling line starts | about 0 s (it lasts about 2 s) |
| Both frames captured | about 1.1 s |
| Line text ready (frames + Claude) | 2.1 to 2.3 s |
| Voice + effect + upload to the Skelly | about 2.8 to 3.0 s |
| With one rejected line and a retry | add about 1.5 s |

With the defaults (`SNAPSHOT_DELAY=1`, `SNAPSHOT_GAP=1`) expect about a second more.
