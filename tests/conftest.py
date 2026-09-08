"""Shared fixtures for the classnotes-agent test suite.

Two kinds of tests live in this suite:

1. "Real" tests against code that already exists in scripts/ today
   (check-coverage.py, verify-notes.py, extract-signals.py, term-coverage.py) --
   these run for real, right now, no skipping. They exercise pure functions
   pulled out of those scripts via import_script().

2. "Contract" tests against the classnotes/ Python package another agent
   (pybuild) is building in parallel, on branch feat/python-pipeline. That
   code does not exist in THIS worktree (it's on main, with no classnotes/
   package yet), so these tests call require_classnotes() first and skip
   cleanly -- not a failure -- until the branches are merged. They encode the
   published CLI contract and become meaningful the moment the code lands.

Never reads or writes the user's real ~/class-notes/ data. classnotes_root
builds a throwaway tree under pytest's tmp_path instead.
"""
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SCRIPTS = REPO_ROOT / "scripts"
FIXTURES = TESTS_DIR / "fixtures"


def import_script(filename):
    """Import a hyphenated script from scripts/ as a module, by file path.

    These are real, already-implemented scripts (not the classnotes/ package),
    so importing them exercises real production code today. Only the module-
    level defs run on import -- every script guards its side-effecting main()
    behind `if __name__ == "__main__":`.
    """
    path = SCRIPTS / filename
    if not path.exists():
        pytest.skip(f"{filename} not found at {path}")
    modname = "cn_" + filename.replace("-", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def has_classnotes_package():
    return importlib.util.find_spec("classnotes") is not None


def require_classnotes():
    """Call at the top of a test that needs the classnotes/ package itself.

    Skips (not fails) when pybuild's feat/python-pipeline branch hasn't been
    merged into this worktree yet -- that is expected today.
    """
    if not has_classnotes_package():
        pytest.skip(
            "classnotes package not importable yet -- waiting on "
            "feat/python-pipeline to land"
        )


def run_cli(*args, env=None, cwd=None, timeout=30):
    """Invoke `python3 -m classnotes <args>` as a subprocess.

    Tests the published CLI contract as a black box, decoupled from
    pybuild's internal module/function names -- only the command-line
    surface described in the task contract is assumed.
    """
    require_classnotes()
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "classnotes", *args],
        capture_output=True, text=True, env=full_env, cwd=cwd, timeout=timeout,
    )


@pytest.fixture
def classnotes_root(tmp_path):
    """A throwaway ~/class-notes/-shaped tree, isolated from real user data."""
    root = tmp_path / "class-notes"
    root.mkdir()
    (root / "models").mkdir()
    # transcribe.sh refuses to run if the model file is absent, so it would never
    # reach the stubbed whisper-cli. These are placeholders -- the stub never
    # reads them. Without this the whisper-safety tests pass only on a machine
    # that happens to have the real 1.6 GB model downloaded.
    (root / "models" / "ggml-large-v3-turbo.bin").write_bytes(b"not a real model")
    (root / "models" / "ggml-silero-v5.1.2.bin").write_bytes(b"not a real model")
    (root / "courses.yaml").write_text(
        (FIXTURES / "sample_courses.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "cancellations.yaml").write_text(
        (FIXTURES / "sample_cancellations.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    for slug in ("intro-statistics", "microeconomics"):
        c = root / slug
        (c / "raw").mkdir(parents=True)
        (c / "transcripts").mkdir()
        (c / "lectures").mkdir()
    return root


_WHISPER_STUB = '''#!/usr/bin/env python3
"""Fake whisper-cli: logs its argv, then writes a plausible-looking
.txt (+ .srt) at whatever -of basename it was given, instead of doing any
real transcription. Word count of the .txt is controlled by the
CLASSNOTES_TEST_WHISPER_WORDS env var (default 40), so density-guard tests
can dial in an exact match or mismatch.
"""
import os
import sys

log = os.environ["CLASSNOTES_TEST_LOG"]
with open(log, "a") as f:
    f.write(sys.argv[0] + " " + " ".join(sys.argv[1:]) + "\\n")

of = None
args = sys.argv[1:]
for i, a in enumerate(args):
    if a == "-of" and i + 1 < len(args):
        of = args[i + 1]

if of:
    os.makedirs(os.path.dirname(of) or ".", exist_ok=True)
    n = int(os.environ.get("CLASSNOTES_TEST_WHISPER_WORDS", "40"))
    with open(of + ".txt", "w") as f:
        f.write(" ".join(f"word{i}" for i in range(n)) + "\\n")
    with open(of + ".srt", "w") as f:
        f.write("1\\n00:00:00,000 --> 00:00:01,000\\nstub\\n\\n")
sys.exit(0)
'''

_LOGGING_STUB = '''#!/usr/bin/env python3
import os, sys
log = os.environ["CLASSNOTES_TEST_LOG"]
with open(log, "a") as f:
    f.write(sys.argv[0] + " " + " ".join(sys.argv[1:]) + "\\n")
{extra}
sys.exit(0)
'''


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    """A directory prepended to PATH holding stub whisper-cli/ffmpeg/ffprobe
    binaries that log their argv to a file instead of doing real work. Lets
    contract tests assert on exactly what command the pipeline builds
    without ever invoking real whisper, touching audio, or hitting the
    network. See density.py / transcribe.sh for why ffprobe must print a
    number check-coverage.py can parse as a duration.
    """
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    log = tmp_path / "invocations.log"

    def make_stub(name, source):
        p = bindir / name
        p.write_text(source)
        p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    make_stub("whisper-cli", _WHISPER_STUB)
    make_stub("ffmpeg", _LOGGING_STUB.format(extra=""))
    make_stub("ffprobe", _LOGGING_STUB.format(extra='print("1.0")'))

    monkeypatch.setenv("CLASSNOTES_TEST_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    return bindir, log
