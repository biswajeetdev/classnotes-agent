"""Density check: did the kept transcript actually capture the lecture.

Measured failure (LESSONS.md, policy-ethics-legal): a transcript's raw
words-per-minute can look low for two different reasons -- whisper dropped a
sustained stretch in the minority language, or the professor just talks
slowly. The only way to tell them apart is to re-transcribe one chunk with
the language forced and compare word counts against what's already there.
On 2026-09-06 that was chunk-0017: 451 words against 451 -- an exact match,
so the low wpm was cadence, not loss.

This automates exactly that check using the per-chunk .wav/.txt pairs
live-notes.sh already keeps under raw/<date>-live/ -- no re-transcription of
anything not already re-verifiable, and no need for a human-maintained
capture log. Falls back to reporting "unverifiable" (never silently "ok")
when no live-chunk pairs exist -- e.g. a single Teams .mp4 download with no
chunked capture.

Deliberately does NOT use check-coverage.py on a .txt -- that needs an .srt
timeline and false-reports 100% missing without one (see SKILL.md step 2 and
scripts/check-coverage.py's own docstring).
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config

MIN_CHUNK_WORDS = 20  # skip near-silent chunks -- picking one tells you nothing


def _model_paths() -> tuple[Path, Path]:
    """Resolved at call time (not import time) and relative to the configured
    root (CLASSNOTES_ROOT), not a hardcoded ~/class-notes -- so a sandboxed
    test root is actually honoured. WHISPER_MODEL/WHISPER_VAD_MODEL still
    override explicitly, matching transcribe.sh's own convention."""
    root = config.default_root()
    model = Path(os.environ.get("WHISPER_MODEL", str(root / "models" / "ggml-large-v3-turbo.bin"))).expanduser()
    vad = Path(os.environ.get("WHISPER_VAD_MODEL", str(root / "models" / "ggml-silero-v5.1.2.bin"))).expanduser()
    return model, vad


@dataclasses.dataclass
class DensityResult:
    status: str  # "verified" | "mismatch" | "unverifiable"
    detail: str
    chunk: str | None = None
    original_words: int | None = None
    recheck_words: int | None = None


def _wc(text: str) -> int:
    return len(text.split())


def _dense_chunk(live_dir: Path) -> tuple[Path, Path, int] | None:
    """Pick the chunk with the most words -- a dense chunk, not "the middle
    one" (a middle chunk can land on a silent break and compare 12 to 12,
    which passes without verifying anything)."""
    candidates = []
    for txt in sorted(live_dir.glob("chunk-*.txt")):
        wav = txt.with_suffix(".wav")
        if not wav.exists():
            continue
        n = _wc(txt.read_text(encoding="utf-8", errors="replace"))
        if n >= MIN_CHUNK_WORDS:
            candidates.append((wav, txt, n))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[2], reverse=True)
    return candidates[0]


def _whisper_transcribe_wav(wav: Path, lang: str, outbase: Path) -> Path:
    model, vad_model = _model_paths()
    if not model.exists():
        raise RuntimeError(f"whisper model missing: {model}")
    if not shutil.which("whisper-cli"):
        raise RuntimeError("whisper-cli not installed")
    vad_args = []
    if vad_model.exists():
        vad_args = ["--vad", "--vad-model", str(vad_model), "--suppress-nst"]
    threads = str(os.environ.get("WHISPER_THREADS") or (os.cpu_count() or 4))
    cmd = ["whisper-cli", *vad_args, "-m", str(model), "-f", str(wav), "-l", lang,
           "-t", threads, "-otxt", "-of", str(outbase), "-pp"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = outbase.with_suffix(".txt")
    if r.returncode != 0:
        raise RuntimeError(f"whisper-cli failed: {r.stderr[:400]}")
    return out


def check(live_dir: Path, lang: str) -> DensityResult:
    if not live_dir.exists():
        return DensityResult(
            "unverifiable",
            f"no live-chunk capture at {live_dir} -- cannot mechanically re-verify "
            "density. Proceeding, but this transcript's completeness is unconfirmed; "
            "check it by eye before trusting exam signals drawn from it.",
        )
    picked = _dense_chunk(live_dir)
    if picked is None:
        return DensityResult(
            "unverifiable",
            f"no non-trivial chunk pairs found under {live_dir} -- cannot re-verify density.",
        )
    wav, txt, original_words = picked
    with tempfile.TemporaryDirectory(prefix="classnotes-density-") as td:
        outbase = Path(td) / "recheck"
        try:
            recheck_txt = _whisper_transcribe_wav(wav, lang, outbase)
        except RuntimeError as e:
            return DensityResult("unverifiable", f"density recheck could not run: {e}",
                                  chunk=wav.name, original_words=original_words)
        recheck_words = _wc(recheck_txt.read_text(encoding="utf-8", errors="replace"))

    tolerance = max(3, round(original_words * 0.05))
    diff = abs(recheck_words - original_words)
    if diff <= tolerance:
        return DensityResult(
            "verified",
            f"density check ok: {wav.name} re-transcribed forced -l {lang} gave "
            f"{recheck_words} words against the kept {original_words} (diff {diff}, "
            f"tolerance {tolerance}) -- transcript looks complete.",
            chunk=wav.name, original_words=original_words, recheck_words=recheck_words,
        )
    return DensityResult(
        "mismatch",
        f"!! DENSITY MISMATCH on {wav.name}: kept transcript has {original_words} words, "
        f"forced -l {lang} recheck got {recheck_words} (diff {diff}, tolerance {tolerance}). "
        "This transcript may be missing a sustained stretch of speech in another language. "
        "Do not silently proceed -- inspect and, if needed, run the full gap-recovery "
        "procedure in SKILL.md step 2 before trusting this transcript's exam signals.",
        chunk=wav.name, original_words=original_words, recheck_words=recheck_words,
    )
