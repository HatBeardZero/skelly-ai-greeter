# Personas

A persona is a voice. Each one is a file in `personas/`, and the file name is its name
(`crypt.toml` is `crypt`). The visitor-safety rules (no comments on bodies, no threats,
nothing about what the camera sees, plain English) live in code and are added to every
persona, so a new persona only has to say how it sounds.

| Persona | Use |
|---|---|
| `crypt` | Halloween door greeter. Dry and theatrical, with a small creepy sting on any compliment. |
| `exhibition` | A silent exhibit that suddenly speaks. Aims for a gasp, then a laugh. No Halloween talk. |

## Choosing one

- **Hard setting:** add `PERSONA=exhibition` to `~/.skelly_env` and restart the service.
  The default is `crypt`.
- **Routing rule:** send `persona` in the Home Assistant call, for example a different value
  per camera, time of day, or toggle. A missing, empty or unknown name uses the hard setting.

```yaml
- action: rest_command.skelly_greet
  data:
    camera: <YOUR_FRIGATE_CAMERA_NAME>
    persona: "{{ 'exhibition' if is_state('input_boolean.skelly_exhibit', 'on') else 'crypt' }}"
```

## Writing a new one

Copy `personas/crypt.toml` and change:

- `description`: a note for you.
- `tone`: who the voice is, how it sounds, and a few example lines (the model is told never
  to reuse them word for word).
- `fallbacks`: canned lines spoken if the AI step fails.

Names may use only lowercase letters, digits, `_` and `-`. Lines still pass the word filter
in `line_ok`, which is shared across personas. Test a new one by sending a greeting and
reading the `Skelly says (<persona>):` log line.
