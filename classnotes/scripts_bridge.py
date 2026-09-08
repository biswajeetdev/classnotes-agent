"""Subprocess wrappers around the existing scripts/ tools.

This package consolidates and orchestrates those scripts rather than
reimplementing their logic -- transcribe.sh's whisper-cli invocation,
digest.py's Groq pacing for the digest pass, extract-signals.py's regex
extraction, and verify-notes.py's grounding checks are all measured, working
code. Wrapping them as subprocesses (instead of importing) keeps this package
decoupled from their internals and lets each keep its own CLI contract.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


class ScriptError(Exception):
    def __init__(self, msg, returncode=1):
        super().__init__(msg)
        self.returncode = returncode


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def transcribe(input_media: Path, outbase: Path, lang: str = "auto", force: bool = False) -> tuple[Path, Path]:
    """Runs scripts/transcribe.sh. Returns (txt_path, srt_path).

    Raises ScriptError with transcribe.sh's stderr on failure (e.g. missing
    ffmpeg/whisper-cli, or an existing transcript refusing to be clobbered).
    """
    cmd = [str(SCRIPTS_DIR / "transcribe.sh"), str(input_media), str(outbase), lang]
    env = os.environ.copy()
    if force:
        env["FORCE"] = "1"
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    txt, srt = Path(f"{outbase}.txt"), Path(f"{outbase}.srt")
    # transcribe.sh's own coverage check exits non-zero on flagged gaps (see
    # check-coverage.py) but still writes a transcript -- that's a warning to
    # surface, not necessarily a hard failure of transcription itself.
    if not txt.exists() or txt.stat().st_size == 0:
        raise ScriptError(f"transcribe.sh produced no transcript:\n{r.stdout}\n{r.stderr}", r.returncode)
    return txt, srt, r.stdout + r.stderr, r.returncode


def digest(transcript: Path, out: Path | None = None) -> tuple[Path, str]:
    """Runs scripts/digest.py. Returns (digest_path, combined_output)."""
    out = out or transcript.with_name(transcript.stem + "-digest.md")
    r = _run(["python3", str(SCRIPTS_DIR / "digest.py"), str(transcript), str(out)])
    if r.returncode != 0 or not out.exists():
        raise ScriptError(f"digest.py failed:\n{r.stdout}\n{r.stderr}", r.returncode)
    return out, r.stdout + r.stderr


def extract_signals(transcript: Path) -> str:
    """Runs scripts/extract-signals.py. Returns its verbatim stdout."""
    r = _run(["python3", str(SCRIPTS_DIR / "extract-signals.py"), str(transcript)])
    if r.returncode != 0:
        raise ScriptError(f"extract-signals.py failed:\n{r.stderr}", r.returncode)
    return r.stdout


def verify_note(note: Path, transcript: Path) -> tuple[bool, str]:
    """Runs scripts/verify-notes.py. Returns (clean, output)."""
    r = _run(["python3", str(SCRIPTS_DIR / "verify-notes.py"), str(note), str(transcript)])
    return r.returncode == 0, r.stdout + r.stderr


def term_coverage(root: Path, args: list[str]) -> tuple[int, str]:
    """Runs scripts/term-coverage.py. Returns (exit_code, output).

    term-coverage.py reads its own ROOT from the CLASSNOTES_ROOT env var (not
    cwd -- it never looked at cwd, so passing cwd=root here used to be a no-op
    that looked like it worked). Set the env var explicitly from `root` rather
    than relying on it already being set in the ambient environment, so this
    always matches whatever Paths/config resolved root to.
    """
    env = os.environ.copy()
    env["CLASSNOTES_ROOT"] = str(root)
    r = subprocess.run(["python3", str(SCRIPTS_DIR / "term-coverage.py"), *args],
                        capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr
