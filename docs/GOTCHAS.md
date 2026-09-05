# Gotchas

Every item here cost a real lecture or a real hour. They are recorded with the
measurement that produced them, because "trust me" is not useful to anyone else.

---

## Transcription

### Never pass `-bs 1` to whisper-cli
It exits `rc=0` in under a second and writes **no transcript at all**. It looks like a
400× speedup and is total silent failure. There is no error to catch — check that the
output file exists and is non-empty.

### Whisper locks onto ONE language per file
On code-switched audio, whisper commits to the dominant language and **silently drops
sustained speech in the other**. No error, no gap marker in the output.

Measured on two code-switched samples (turbo model):

| sample | `auto` | forced minority language |
|---|---|---|
| majority English + Hindi | all kept, Hindi romanised | all kept |
| majority Hindi + English | **English sentence DROPPED** | all kept, but Hindi **translated** + a hallucinated line |

What survives fine: English technical terms embedded mid-sentence. Ordinary
code-switching is not the problem. **Sustained stretches in the minority language are** —
student Q&A in English during a Hindi lecture is the realistic case.

Never use translation mode (`-tr`) to "fix" this. It replaces one lossy failure with
another and adds hallucination.

### Measure the loss before you spend an hour recovering it
A forced-language re-pass takes ~40 minutes for a 90-minute lecture. Don't do it blindly.
Re-run **one chunk** with the language forced and compare word counts:

- Counts match → the auto pass locked correctly. Skip recovery.
- Counts diverge → recover everything.

On one lecture the auto pass lost 20–25% of the words. On another, nine chunks out of
nine matched exactly. Same professor, same microphone. **Always check; never assume.**

### Hallucination on silence
Whisper invents fluent, plausible speech to fill silence. Real examples from one term:

- *"Any doubt in this notebook? I think it is very easy to do."* — **32×**
- *"You said that you had a lot of money"* — **77×** (a phone call near the mic)
- *"Thank you."* — **45×**
- *"\*click\*"*, *"\*sad music\*"*, *"We'll be right back"* — from an empty room

**Fix: enable VAD.** whisper.cpp ≥ 1.9 has Silero VAD built in:

```
--vad --vad-model models/ggml-silero-v5.1.2.bin
```

Measured on one 5-minute chunk:

| | without VAD | with VAD |
|---|---|---|
| fabricated lines | 36 | **0** |
| real words | 466 | **515** — it *recovered* speech |
| a technical term | wrong | **correct** |
| runtime | ~35s | **27s** |

**Side effect to handle:** with VAD on, a chunk containing no speech produces **no `.txt`
at all**. That is correct, not a failure — but code that unconditionally reads the output
will print `No such file or directory`, which is the same signature a dead recorder
produces. Guard the read.

Even with VAD, **read the tail of every transcript** before trusting it. Repetition
detectors cannot distinguish invented repetition from genuine emphasis.

### Live-coding narration is not emphasis
A professor who narrates his typing produces phrases like *"Now I am going to write a
double quote"* **145 times** in one lecture. Repetition-based signal extraction will rank
these as the most emphasised lines in the class. Discard them by hand.

---

## Live capture

### Back-to-back classes defeat the silence auto-stop
Capture stops itself after sustained silence, on the assumption that silence means the
class ended. When the next class starts immediately on the same audio path, **the room
never goes quiet** — so the recorder runs straight on and files one course's lecture
under another. That corrupts the second course's synthesis.

On stacked days, stop the earlier capture manually **before** the next one starts.

### Switching audio output mid-class kills the recording
Capture taps a virtual device (BlackHole) fed by a Multi-Output device. Selecting AirPods,
or any other output, **bypasses that Multi-Output** — the recorder goes deaf while the
class continues. The audio chain is typically verified once at startup, so a later switch
is invisible: you get silence, then the auto-stop concludes the class is over.

Two defences, both in this repo:
- `live-notes.sh` records the output device at start and compares before ever concluding
  "class is over" — a mismatch warns loudly and resets the silence counter.
- `check-audio.sh` is a 4-second probe you can run any time mid-class.

Bluetooth-specific hazard: if a meeting app grabs the AirPods **microphone**, macOS
switches them to the hands-free profile, changing sample rate and device identity.

### Stopping one capture can kill another running concurrently
Observed when two captures overlapped: stopping the first switched the system output
device, and the second capture's ffmpeg died immediately, writing a zero-word transcript.
All kills are by PID, so this is not a stray global `pkill` — the likely mechanism is
avfoundation device indices shifting under a process that opened a device by index.

After any stop on a day with overlapping sessions, check the other capture's log for
`0 words`.

### Slide capture silently produces zero frames without permission
ffmpeg runs, exits cleanly, logs only a benign `NSKVONotifying_AVCaptureScreenInput`
message, and writes no JPEGs. Indistinguishable from success unless you count the files.

Grant **Screen Recording** permission to your terminal in
System Settings → Privacy & Security. Note that encoder or pixel-format errors produce
*identical* symptoms, so check the ffmpeg log too.

Prefer the lecturer's own uploaded slides where they exist — real text, nothing clipped,
and they include slides clicked past too fast to read.

### Delayed `sleep` launchers do not fire
`nohup bash -c "sleep N; exec capture.sh"` armed 18 minutes ahead overran its deadline and
never exec'd. Use launchd with `StartCalendarInterval` for anything time-triggered.

### `stop` blocks, and killing it orphans the recorder
Stopping waits while the final chunk transcribes — minutes, not seconds. Killing the
wrapper does **not** kill the ffmpeg child, which keeps writing chunks unattended. Kill
that PID explicitly and clear the state directory before restarting.

---

## Scheduling

### launchd runs with a minimal PATH
`StartInterval` jobs get `/usr/bin:/bin:/usr/sbin:/sbin`, which excludes Homebrew. Every
tool the capture chain needs lives in `/opt/homebrew/bin`, so a scheduled capture logs
"start" and then dies instantly on `whisper-cli missing`. Export the PATH explicitly at
the top of any launchd-invoked script; children inherit it.

### Never mark a slot "done" before the child is alive
Writing the done-marker before launching means a child that dies on a missing dependency
is indistinguishable from a completed class — every later check skips it and the lecture
is lost in silence. Verify with `kill -0` a few seconds after launch, then mark.

### A schedule change breaks anything that duplicates the timetable
When a timetable is revised, every hand-maintained copy drifts. One calendar kept ringing
for classes that no longer existed and stayed silent for the two that replaced them.
Generate derived artefacts (`gen-calendar.py`) from `courses.yaml`; never hand-edit them.

An iCalendar event whose `DTSTART` weekday contradicts its `RRULE` `BYDAY` is malformed,
and clients resolve it by showing nothing until the next matching weekday — which can be
months away. Always check the two agree.

### Same-day restarts are refused
Capture aborts if a transcript already exists for that date, but the wrapper may print its
success banner first, so the failure is easy to miss. Move the old transcript aside, or
use a per-session suffix.

---

## Note quality

### Verify the finished note against the transcript
`verify-notes.py` checks every figure, direct quote and proper noun. On the first two
notes this pipeline produced it found four real errors. On a later note it caught **eight
places where a paraphrase had been presented inside quotation marks**.

Rules when it flags something:
- **A quote that does not match** — use what was actually said, or drop the quotation
  marks. Never present a paraphrase as a quote.
- **A name the transcript never contains** — it is a reconstruction. Declare it or remove
  it.
- **A number with no source** — delete it. Do not "remember" figures.

### A summariser will drop the single most important sentence
An LLM digest of one lecture invented nothing and still lost the two highest-value lines —
an explicit exam signal, and the professor's one-sentence thesis. Summarisers optimise for
topic coverage and have no notion that one sentence outweighs a paragraph.

Build exam-signal sections from deterministic extraction (`extract-signals.py`), which
greps for assessment language and returns the speaker's words untouched. Use the digest
only for navigation.

### Never attribute a line to a named student
No speaker diarization is available, and misattributing a classmate is worse than a gap.
Record Q&A as "a student asked… the professor answered…".

### Write `[unclear: best guess]` rather than inventing
A wrong note found the night before an exam is worse than a gap. Record what you
reconstructed, so it can be checked against the slides later.
