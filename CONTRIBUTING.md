# Contributing

## The most valuable contribution is a measured failure

This project is mostly defences against ways speech recognition fails quietly on real
lectures. If whisper drops, invents or garbles something on your audio, a reproduction
**with numbers** is worth more than a fix:

- the model and flags you used
- word counts before and after, or the fabricated line and how many times it appeared
- roughly what the audio was (language mix, room, microphone)

Claims in `docs/GOTCHAS.md` carry their measurement for exactly this reason. Please keep
that convention — if you add a gotcha, add the evidence that produced it.

## Ground rules

- **Never commit class material.** The `.gitignore` is deny-by-default at the repository
  root. Do not weaken it. Check `git status` before every commit.
- **Never commit secrets.** `.env` is ignored; keep it that way.
- **Fail loudly.** The recurring theme of every bug here is a failure that looked like
  success. A script that cannot do its job should say so, not exit 0.
- **Keep files under 500 lines.**
- Shell scripts: `set -uo pipefail`, `bash -n` clean. Python: standard library only where
  possible, no new dependencies without a reason.

## Testing

There is no test suite; the inputs are hours of audio. Before opening a PR, confirm:

```bash
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
```

and that a real recording still transcribes end to end.

## Scope

In scope: capture reliability, transcription accuracy, note structure, verification,
anything that stops a lecture being lost.

Out of scope: cloud transcription services, anything requiring credentials for a
university system, and features that upload class audio anywhere by default.
