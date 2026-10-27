# Halloween night checklist

## Before the night (finish a day or two early)

- [ ] Copy the latest `skelly_greeter.py` to `~/skelly_greeter.py`, then
      `systemctl --user restart skelly-greeter`.
- [ ] Test an empty frame, a hat, and a mask from the Home Assistant action
      (`rest_command.skelly_greet`). No foreign words, no comments about hair or glasses,
      and nothing about what the camera "can see". A stalling line plays first.
- [ ] **Placement test after dark**, with the Skelly and Pi in their final spots and the
      porch light on. Trigger three or more times from where a visitor stands. Can you
      understand it over street noise? Does audio break up? Does the speaker link survive
      between triggers?
- [ ] Test the schedule's off branch: toggle on, set the "off" trigger two minutes ahead,
      confirm it switches the toggle off, set it back.
- [ ] Reboot test: `sudo reboot`, wait two minutes, confirm the Skelly's speaker sink is back.
- [ ] Take a Home Assistant backup and do not update anything after it.
- [ ] Put up a sign saying a camera and AI are in use.
- [ ] Dry run the night before: toggle on, press the doorbell, toggle off.

## Settings for the night

Frames are not kept locally by default (`SAVE_SNAPSHOT=0`). If you turned it on while
debugging, switch it off, restart the greeter, and delete the saved frames:

```
systemctl --user restart skelly-greeter
rm -f /tmp/last_snapshot*.jpg
```

Each doorbell press still sends two frames (one with `SNAPSHOT_COUNT=1`) to the Claude API to write the line.

## Afternoon

- [ ] Skelly in place and powered. Mode button on **Bluetooth**, volume knob up, phone app
      fully closed.
- [ ] Pi powered and within the range you tested. Porch light on.
- [ ] On the Pi:
      ```
      systemctl --user status skelly-server skelly-greeter --no-pager | head -12
      pactl list sinks short | grep -i <speaker address with _ for :>
      curl localhost:8765/health
      ```
      Expect both services `active (running)`, the sink `RUNNING`, and `{"status": "ok"}`.
- [ ] Home Assistant: the template `{{ now().month == 10 and now().day == 31 }}` shows True
      on the day, and the time zone is right.
- [ ] Fire one greeting from the HA action and confirm the Skelly speaks.

## Just before the first visitors

- [ ] The toggle turns on at the scheduled time only if Home Assistant is up. Check it, and
      switch it on by hand if not.
- [ ] The toggle and the time window in the doorbell automation both have to say yes.
      If trick-or-treating runs outside the window, change both places.

## During the night

Normal: a stalling line within about a second of the press, then the AI line about three
seconds after the press. `journalctl --user-unit skelly-greeter -f` shows it live.

- `Rejected line, trying again:` is normal; the checker caught a line and asked for a new one.
- `AI step failed, using fallback:` means the Claude call failed and a canned line was used.
- A press during a greeting, or within the cooldown, is ignored on purpose.

## If something goes wrong

| Symptom | Check | Fix |
| --- | --- | --- |
| Press does nothing | Automation traces: toggle on? time inside the window? | Switch the toggle on or fix the time condition |
| Trace shows the action ran, no sound | `pactl list sinks short` has no Skelly line | Wait 30 s for the auto reconnect, else restart both services |
| Log says it played, silence | Mode button not on Bluetooth, or default sink is `auto_null` | Set the mode button, restart the bridge |
| Only canned lines | `journalctl ... -n 30` shows `AI step failed` | Check the API key and credit balance |
| Choppy audio | Distance or walls to the Skelly | Move the Pi closer or use a USB dongle on an extension cable |
| Line you don't like | Note it from the log | Switch the toggle off at once. The checker is a blunt filter, not a guarantee |

## After the night

- [ ] Toggle off. Disable the schedule automation if you do not want it to turn the
      greeter on again next Oct 31.
- [ ] Stop the services if the Skelly goes into storage:
      `systemctl --user disable --now skelly-greeter skelly-server`.
- [ ] Delete the API key in the Anthropic Console if you will not reuse it, and remove
      `~/.skelly_env`.
