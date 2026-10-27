# Dialing it in

`SETUP.md` gets the pieces running. This guide is the part that took the longest: making it
reliable, fast, understandable and well behaved. It is written in the order we hit the
problems, and every step says what to look at, what we found, and what we changed.

Rules that saved time:

- **Change one thing at a time**, then test again.
- **Judge sound on the Skelly's own speaker**, from where visitors will stand, with a
  full-length greeting. A laptop speaker and a short test phrase both mislead.
- **Watch the log while you test:** `journalctl --user-unit skelly-greeter -f`.
- **Re-check that the running service has the setting you think it has** (see "Verify the
  running service" below). We lost time tuning a value the service was not using.

## 0. A test harness that doesn't need the doorbell

Trigger a greeting without ringing the bell, and give yourself time to walk to the door:

```
sleep 15; curl -X POST localhost:8766/greet -H "Content-Type: application/json" \
  -d '{"camera": "<your frigate camera>"}'
```

From Home Assistant, Settings, Tools, Actions, `rest_command.skelly_greet` does the same
and works from a phone. This ignores the toggle and the time window. There is a cooldown
(default 20 s), so wait between tests.

While tuning, turn on frame saving so you can see exactly what Claude was shown:

```
echo 'SAVE_SNAPSHOT=1' >> ~/.skelly_env && systemctl --user restart skelly-greeter
scp <user>@<pi>:/tmp/last_snapshot_1.jpg .     # and _2
```

When you are finished, remove that line, restart, and `rm -f /tmp/last_snapshot*.jpg`.

### Verify the running service

```
systemctl --user status skelly-greeter --no-pager | head -4
tr '\0' '\n' < /proc/$(systemctl --user show -p MainPID --value skelly-greeter)/environ \
  | grep -E "SOX_EFFECT|SNAPSHOT_|FILLER_DIR|SKELLY_|FRIGATE"
```

If a value is wrong, look for it in two places: `~/.skelly_env` and an `Environment=` line
in `~/.config/systemd/user/skelly-greeter.service`. In our case an old `Environment=` line
in the unit file beat the env file, so keep each setting in one place. After editing the
unit file run `systemctl --user daemon-reload`; after either, restart the service.

## 1. Make the speaker link reliable

**Symptoms:** it works, then goes silent; the Skelly beeps as it connects and disconnects;
the log keeps printing `reconnecting`.

**Find out whether the link is really up.** The bridge reports "playing" even when it is
not, because PipeWire plays into a dummy sink. Watch the real thing:

```
while true; do date +%T; pactl list sinks short | grep -c <speaker address with _ for :>; sleep 15; done
```

`1` means the Skelly's speaker sink exists, `0` means it is gone.

**What we found:** the sink disappeared every 2 to 5 minutes while idle. The Skelly drops
its speaker link when its BLE control link goes quiet.

**Experiment that fixed it:** send a harmless BLE query to the Skelly every 20 seconds. With
that running, the sink stayed at `1` for over an hour with no drops. The greeter now does
this itself (`KEEPALIVE_SECONDS`), checks the sink before each greeting, and reconnects when
it is missing.

Other causes to rule out when audio is silent:

- The Skelly's **mode button** is not on Bluetooth, or the **volume knob** is down.
- The phone app is open (it holds the Skelly's single BLE connection).
- The Pi is on a **guest network**, so it cannot reach Home Assistant or Frigate.
- The Pi is too far from the Skelly. Test at the final distance.
- Weak power: `vcgencmd get_throttled` should print `0x0`.

**Bluetooth radio:** the bridge's README recommends a USB dongle over the Pi's onboard radio.
Ours played well from the onboard radio at about 15 ft, so we kept it. One dongle (ASUS
USB-BT600) never initialised on our kernel. If you try a dongle, check
`dmesg | grep -i bluetooth` for init failures, and test audio at the final distance.

**Prove it survives a reboot:** `sudo reboot`, wait two minutes, and check the sink is back
with nobody touching anything. This is the test that matters for a power blip.

## 2. Camera frames Claude can use

Check the frame the greeter will fetch, from the Pi:

```
time curl -s -o /tmp/a.jpg "<FRIGATE_URL>/api/<camera>/latest.jpg?h=720"
sleep 1
curl -s -o /tmp/b.jpg "<FRIGATE_URL>/api/<camera>/latest.jpg?h=720"
md5sum /tmp/a.jpg /tmp/b.jpg; file /tmp/a.jpg
```

- **Fast:** under a second (ours was under 0.1 s).
- **Fresh:** the two checksums differ, so the stream is not stalled.
- **Big enough:** a 240x180 frame was useless for reading costumes. 960x720 worked well. If
  yours is tiny, raise the camera's detect resolution in Frigate or use another frame source.

Then look at real frames with someone in a costume standing where visitors will (use
`SAVE_SNAPSHOT=1`). Check the person is large in the frame and the costume is readable.

- **Two frames beat one.** The first frame often catches a visitor mid-motion or looking
  away; the second a moment later is the clean one. That is why `SNAPSHOT_COUNT` is 2.
- **Light:** infrared night mode turns the picture black and white and hides costume
  colors. Turn the porch light on. If your camera lets you force color mode, try it and
  judge a real frame after dark.
- **The yard is in the frame.** Our camera also sees the yard decorations. The model
  commented on the giant skeleton until the prompt told it to ignore decorations.
- **Camera network:** after we improved the camera's Wi-Fi connection, frame fetches were fast
  (under 0.1 s). A weak camera link means slow or stale frames, so fix that first.

## 3. Timing

Each greeting logs `[timing]` lines. What to read:

| Line | Meaning |
| --- | --- |
| `filler ... started 0.0s, lasts 2.1s` | the stalling line starts immediately and lasts this long |
| `N frame(s) captured` | after `SNAPSHOT_DELAY` plus the gaps |
| `line ready` | frames captured plus the Claude call |
| `audio sent to Skelly` | the AI line has been uploaded and playback starts |

**Goal:** the stalling line should cover most of the wait, leaving under a second of
silence before the AI line.

What we changed, and the effect:

| Change | Effect |
| --- | --- |
| Keep the Piper voice loaded in memory | synthesis plus effect plus upload about 0.5 s |
| Thinking off for the Claude call | no wasted time on a one-line reply |
| Stalling lines of 2 to 3 seconds, not under 1 | covers the AI delay |
| `SNAPSHOT_DELAY=0.5`, `SNAPSHOT_GAP=0.5` on a fast camera feed | saves about a second |

Our result: audio sent 2.8 to 3.1 s after the press, against 4.7 s before. A rejected line
(see section 5) adds about 1.5 s, because a second line is requested.

Longer stalling lines are cheap to make: edit `scripts/make_fillers.sh`, delete the old
WAVs, render again. **Always re-render them after changing the voice chain**, or the stalling
line and the AI line sound like two different skeletons.

## 4. The voice

The voice is Piper plus a sox effect chain (`SOX_EFFECT`). The goal is deep, spooky and
**easy to understand on the Skelly's small speaker**.

Make a full-length test line and play it through the real speaker:

```
scripts/voice_options.sh          # plays several chains one after another, labelled
SET=4 TEXT="<a real greeting>" bash scripts/voice_options.sh
```

`SET=1` is a wide first round, `SET=2` a milder one, `SET=3` a clarity round (less reverb,
presence boost), and `SET=4` a pitch ladder where only the pitch changes.

What we learned:

- **`pitch -800`** sounded deeper on a laptop but was hard to understand on the Skelly.
  **`pitch -600`** was clear. The speaker cannot play very low frequencies, so going lower
  mostly made the voice thinner and muddier, not deeper.
- **Heavy overdrive and a fast tremolo growl** (overdrive 15 or more, tremolo 40 Hz or more)
  sounded bad and clipped. Keep grit light.
- **Level:** tremolo plus reverb made the output about 13 dB quieter in our measurements.
  `norm -3` at the end of the chain restores it.
- **Muddy words:** cut the reverb (for example `reverb 20 40 50`) or add a presence boost
  such as `equalizer 2500 1q 6` just before the reverb.
- **Jaw:** if the jaw looks twitchy, drop `tremolo 7 30` first. If it clips, change
  `gain -3` to `gain -6`.
- **Blind tests can mislead.** In an A/B test that plays the two in random order, picking
  "2" every time means you could not hear a difference. And a louder clip tends to win, so
  level-match both chains (`norm -3` on each) before comparing.

**Put the chain in `~/.skelly_env` in double quotes:**

```
SOX_EFFECT="gain -3 pitch -600 bass 6 overdrive 6 tremolo 7 30 reverb 50 50 80 norm -3"
```

Unquoted, systemd still reads it, but `source ~/.skelly_env` in a shell fails with
`bash: -3: command not found` and leaves `$SOX_EFFECT` empty. We played a clip with no
effects at all for a while because of this, and it sounded "too high".

Then re-render the stalling lines, restart the greeter, and run the "verify the running
service" check above.

## 5. The words

Tune the wording with a fixed set of test cases, and read the line each time:

1. nobody in frame
2. a hat or a mask
3. plain clothes
4. a cape or other distinctive costume
5. two or more people

Our model was asked for a spooky host and still needed several rounds. Each problem and fix:

| We saw | Fix |
| --- | --- |
| Cheery, bubbly greetings | Rewrote the prompt as a dry, ominous horror host: no exclamation marks, ellipses for pauses, example lines |
| "amigo" for a sombrero | Prompt rule naming the word, plus a code check that rejects it |
| "Nobody's visible yet" with an empty frame | Prompt: never mention what can be seen; code check on words like visible, see, camera |
| Mentioned the giant skeleton in the yard | Prompt: ignore decorations |
| "Golden glasses" (it was the hat's chin cord) | Prompt: comment on one item only, never on glasses or faces |
| "Not a single costume in sight" | Prompt: never remark on a missing costume; blocked phrases |
| Lines of 18 to 19 words against a 15-word limit | Left as is. The checker allows up to 22 words |

**Why there is a code check at all:** the prompt rules slip. With the rules in place the
model still said "amigo" and still described the empty doorstep. So every generated line is
screened before it is spoken: ASCII only, at most 22 words, no blocked words or phrases. A
rejected line is regenerated once, reusing the same frames, then a canned line is used. You
will see `Rejected line, trying again:` in the log. That is normal and means the check
worked. It is a blunt filter, not a guarantee.

To extend the lists, edit `BANNED_WORDS` and `BANNED_PHRASES` in `skelly_greeter.py` and
test the checker without any hardware:

```
SKELLY_BLE_ADDR=AA:BB:CC:DD:EE:FF SKELLY_CLASSIC_MAC=AA:BB:CC:DD:EE:00 \
FRIGATE_URL=http://x:5000 ANTHROPIC_API_KEY=dummy python3 -c \
 "import skelly_greeter as g; print(g.line_ok('<a line to test>'))"
```

Before the night, run the five test cases above several times and watch for anything you
would not want a child to hear. Keep the toggle within reach on the night.

## 6. Home Assistant

- **Trigger once per press.** Use `to: "on"` on the doorbell sensor, or the automation also
  fires when the sensor turns off again.
- **The toggle and the time window must both pass** before the Skelly speaks. If trick or
  treating runs outside the window, change both the schedule automation and the time
  condition in the doorbell automation. A mismatch gives a toggle that is on and a window
  that is closed, which does nothing and shows no error.
- **Check the schedule's date test** in Developer tools, Template:
  `{{ now().month == 10 and now().day == 31 }}` (false on any other day).
- **Test the schedule's off branch:** turn the toggle on, set the off time two minutes
  ahead, confirm it switches itself off, set it back. The "Run actions" menu skips the
  triggers, so it cannot test this.
- **Read the automation trace** after a real press: one run per press, the `if` branch
  taken, and `rest_command.skelly_greet` called.
- **Configuration slips:** a duplicated top-level key (such as two `http:` blocks) breaks the
  config. Run Check configuration before restarting.
- Recent Home Assistant releases renamed add-ons to "Apps" and moved Developer tools under
  Settings, Tools.

## 7. The final test, after dark

Do this with the Skelly and the Pi in their final positions and the porch light on.

- [ ] Stand where a visitor stands and trigger it several times. Can you understand every
      word over normal street noise?
- [ ] Does the audio ever break up? Does the link survive idle time between greetings?
- [ ] Is the camera good enough in the dark? Read what it says about your costume.
- [ ] Press the real doorbell with the toggle on and the time inside the window.
- [ ] Reboot the Pi and check the speaker comes back by itself.
- [ ] Turn off frame saving, take a Home Assistant backup, and do not update anything after.

Then use `HALLOWEEN_NIGHT_CHECKLIST.md`.

## Quick reference: problem, cause, fix

| Problem | Likely cause | Fix |
| --- | --- | --- |
| "Playing" but silent | Speaker link down, dummy sink; or mode button not on Bluetooth | Check `pactl list sinks short`; set the mode button; restart the bridge |
| Works, then goes silent after minutes | The Skelly drops the speaker link when BLE is idle | The greeter's keepalive (`KEEPALIVE_SECONDS`) |
| Voice sounds high or has no effect | `SOX_EFFECT` unquoted so empty in a shell, or an old value in the unit file | Quote it; keep it in one place; verify the running service |
| Voice hard to understand | Pitch too low, heavy overdrive, too much reverb | Pitch -600, light grit, less reverb, `norm -3` |
| Long silence before the AI line | Stalling line too short, slow snapshot waits | Longer fillers, lower `SNAPSHOT_DELAY` and `SNAPSHOT_GAP` |
| Greeter exits at start | A required setting is missing from `~/.skelly_env` | Add `SKELLY_BLE_ADDR`, `SKELLY_CLASSIC_MAC`, `FRIGATE_URL`, `ANTHROPIC_API_KEY` |
| Only canned lines | The Claude call failed | Check the key and credit balance; read the log for `AI step failed` |
| Press does nothing | Toggle off or outside the time window | Check the toggle and the automation trace |
