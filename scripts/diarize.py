#!/usr/bin/env python3
"""Label who is speaking in a lecture transcript, using whisperX.

    diarize.py <audio.wav> [out.md] [--speakers N]

Notes today flatten every voice into one stream, so a half-heard student question
and the lecturer's answer to it read identically. This separates them: output is
Markdown with one block per turn, each tagged with a speaker.

    **SPEAKER_00** [12:04 – 12:31]
    So the confusion matrix cell order matters a great deal here.

Deliberately a SEPARATE script, not part of transcribe.sh. whisperX pulls in
torch and pyannote (multiple GB), and pyannote's diarization models are gated on
Hugging Face -- you must accept the terms for both `pyannote/segmentation-3.0`
and `pyannote/speaker-diarization-3.1`, then export HF_TOKEN. The main pipeline
must keep working on a machine where none of that is installed, so this stays
opt-in and fails with instructions rather than a traceback.

    pip install whisperx
    export HF_TOKEN=hf_...

NOT VERIFIED END TO END. Written against the whisperX API but never run here --
the install is multi-GB and the models are gated. Treat the first real run as a
test, and check the speaker count before trusting the labels.
"""
import argparse
import os
import sys
from pathlib import Path

HELP = """whisperX is not installed, or its dependencies are missing.

    pip install whisperx

Diarization additionally needs a Hugging Face token, and you must accept the
model terms on the hub first:

    https://huggingface.co/pyannote/segmentation-3.0
    https://huggingface.co/pyannote/speaker-diarization-3.1

    export HF_TOKEN=hf_...
"""


def ts(seconds) -> str:
    if seconds is None:
        return "??:??"
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio")
    ap.add_argument("out", nargs="?", default="")
    ap.add_argument("--speakers", type=int, default=0,
                    help="exact number of speakers, if known — improves accuracy a lot")
    ap.add_argument("--min-speakers", type=int, default=0)
    ap.add_argument("--max-speakers", type=int, default=0)
    ap.add_argument("--model", default=os.environ.get("WHISPERX_MODEL", "large-v3"))
    ap.add_argument("--language", default=os.environ.get("SOURCE_LANG", ""))
    args = ap.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"error: {audio_path} not found", file=sys.stderr)
        return 1

    token = os.environ.get("HF_TOKEN", "").strip()
    try:
        import whisperx
    except Exception:
        print(HELP, file=sys.stderr)
        return 2
    if not token:
        print(HELP, file=sys.stderr)
        return 2

    # CPU on Apple Silicon: whisperX's faster-whisper backend has no Metal path,
    # so float32 on CPU is the honest default here rather than a silent fallback.
    device = os.environ.get("WHISPERX_DEVICE", "cpu")
    compute = os.environ.get("WHISPERX_COMPUTE", "int8" if device == "cpu" else "float16")

    print(f"  transcribing with {args.model} on {device} ({compute})")
    audio = whisperx.load_audio(str(audio_path))
    model = whisperx.load_model(args.model, device, compute_type=compute)
    result = model.transcribe(audio, language=args.language or None)
    lang = result.get("language", args.language or "en")

    print(f"  aligning ({lang}) for word-level timestamps")
    align_model, meta = whisperx.load_align_model(language_code=lang, device=device)
    result = whisperx.align(result["segments"], align_model, meta, audio, device)

    print("  diarizing")
    kw = {}
    if args.speakers:
        kw["num_speakers"] = args.speakers
    if args.min_speakers:
        kw["min_speakers"] = args.min_speakers
    if args.max_speakers:
        kw["max_speakers"] = args.max_speakers
    diarize = whisperx.DiarizationPipeline(use_auth_token=token, device=device)
    result = whisperx.assign_word_speakers(diarize(audio, **kw), result)

    # Merge consecutive segments from the same speaker: a lecture is long turns,
    # and one block per whisper segment would be unreadable.
    turns = []
    for seg in result["segments"]:
        who = seg.get("speaker", "UNKNOWN")
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if turns and turns[-1]["who"] == who:
            turns[-1]["text"] += " " + text
            turns[-1]["end"] = seg.get("end")
        else:
            turns.append({"who": who, "text": text,
                          "start": seg.get("start"), "end": seg.get("end")})

    out_path = Path(args.out) if args.out else audio_path.with_suffix(".speakers.md")
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(f"<!-- diarized from {audio_path.name} via whisperX "
                 f"({args.model}). Speaker labels are inferred — check them. -->\n\n")
        for t in turns:
            fh.write(f"**{t['who']}** [{ts(t['start'])} – {ts(t['end'])}]\n\n{t['text']}\n\n")

    speakers = sorted({t["who"] for t in turns})
    print(f"  wrote {out_path} — {len(turns)} turns, {len(speakers)} speakers: "
          f"{', '.join(speakers)}")
    if len(speakers) > 4:
        print("  note: more speakers than a lecture usually has. Pass --speakers N "
              "if you know the count.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
