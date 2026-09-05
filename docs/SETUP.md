# Setup

## Requirements

macOS. Everything runs locally.

```bash
brew install whisper-cpp ffmpeg switchaudio-osx
brew install --cask blackhole-2ch      # live capture only
```

`whisper-cpp` must be **1.9 or newer** for VAD support:

```bash
whisper-cli --help | grep -- --vad     # should print VAD options
```

## Models

```bash
export CLASSNOTES_ROOT="$HOME/class-notes"
mkdir -p "$CLASSNOTES_ROOT/models"

# transcription, ~1.6 GB
curl -L -o "$CLASSNOTES_ROOT/models/ggml-large-v3-turbo.bin" \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin

# voice activity detection, ~900 KB — this is what stops hallucination
curl -L -o "$CLASSNOTES_ROOT/models/ggml-silero-v5.1.2.bin" \
  https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin
```

Expect roughly **5× realtime** on turbo at full threads — a 90-minute lecture takes about
18 minutes. VAD makes it faster by skipping silence.

## Your timetable

```bash
cp courses.example.yaml "$CLASSNOTES_ROOT/courses.yaml"
```

Use **24-hour times**. An AM/PM misreading once made an 8 PM class invisible to the
scheduler for a fortnight. Create a directory per course slug:

```bash
mkdir -p "$CLASSNOTES_ROOT/<course-slug>"/{raw,transcripts,lectures,slides}
```

## Live capture

Two one-time steps.

**1. Multi-Output Device** — so class audio reaches both your speakers and BlackHole:

```bash
python3 scripts/make-multiout.py
```

It builds the device directly through CoreAudio; Audio MIDI Setup is not needed. The name
must not contain "BlackHole" (there is a guard that refuses to record when the output
device looks like the loopback, so you cannot sit through a silent class).

**2. Screen Recording permission**, if you want slide capture:
System Settings → Privacy & Security → Screen Recording → enable your terminal.

Without it, ffmpeg runs and writes **zero frames** with no error.

Verify before you rely on it:

```bash
scripts/class-start.sh <course-slug>
scripts/check-audio.sh          # should report audio IS reaching the recorder
```

## Optional: Groq digest

Only needed for transcripts over ~4,000 words, and only for navigation — never as the
source of truth.

```bash
cp .env.example "$CLASSNOTES_ROOT/.env"
chmod 600 "$CLASSNOTES_ROOT/.env"
```

This is the **only** part of the pipeline that sends anything off your machine.

## Claude Code skill

```bash
mkdir -p ~/.claude/skills/classnotes
cp skill/SKILL.md ~/.claude/skills/classnotes/SKILL.md
```

Then `/classnotes` in Claude Code, from `$CLASSNOTES_ROOT`.
