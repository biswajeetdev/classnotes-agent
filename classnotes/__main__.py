"""CLI entry point.

    python3 -m classnotes run <course-slug> [<input.mp4> | --date YYYY-MM-DD]
    python3 -m classnotes note <course-slug> <date>
    python3 -m classnotes synthesis <course-slug>
    python3 -m classnotes verify <note.md> <transcript.txt>
    python3 -m classnotes status [--from DATE] [--all]

Run from anywhere; reads real ~/class-notes by default (override with
CLASSNOTES_ROOT). Writes go to the same root unless --out-root redirects them
-- always use --out-root for test runs so nothing under the real tree is
touched (see README's Testing section).
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

from . import config, density, groq_client, notewriter, scripts_bridge, synthesis

TEAMS_FILENAME_DATE = re.compile(r"-(\d{4})(\d{2})(\d{2})-\d{6}-")


def _resolve_date(input_path: Path | None, explicit: str | None) -> str:
    if explicit:
        datetime.date.fromisoformat(explicit)  # raises if malformed
        return explicit
    if input_path is not None:
        m = TEAMS_FILENAME_DATE.search(input_path.name)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return datetime.date.fromtimestamp(input_path.stat().st_mtime).isoformat()
    raise SystemExit("error: no date given and no input file to infer it from -- pass --date")


def _paths(args) -> config.Paths:
    root = config.default_root()
    out_root = Path(args.out_root).expanduser() if getattr(args, "out_root", None) else None
    return config.Paths(root, out_root)


def cmd_run(args):
    root = config.default_root()
    config.load_env(root)
    paths = _paths(args)
    course = config.resolve_course(root, args.course)
    lang = args.lang or config.course_lang(course)

    input_path = Path(args.input).expanduser() if args.input else None
    date = _resolve_date(input_path, args.date)
    print(f">> course: {course.slug} ({course.name}) · date: {date} · lang: {lang}")

    transcript_path = paths.transcript(course.slug, date)
    if transcript_path.exists():
        print(f">> reusing existing transcript: {transcript_path}")
    else:
        if input_path is None:
            raise SystemExit(f"error: no transcript at {transcript_path} and no input media given")
        if not input_path.exists():
            raise SystemExit(f"error: no such input file: {input_path}")
        print(f">> transcribing {input_path.name} (lang={lang}) -- this takes a while")
        if args.dry_run:
            print("   dry-run: would call transcribe.sh here")
        else:
            outbase = transcript_path.with_suffix("")
            txt, srt, log, rc = scripts_bridge.transcribe(input_path, outbase, lang)
            print(log)
            if rc != 0:
                print("!! transcribe.sh's own coverage check flagged gaps -- see '!!' lines above.")

    if args.dry_run:
        print(">> dry-run: skipping density check, note, and synthesis")
        return

    dres = notewriter.density_check(paths, course, date, lang)
    print(f">> density: [{dres.status}] {dres.detail}")
    if dres.status == "mismatch" and not args.force:
        raise SystemExit(">> aborting: density mismatch not acknowledged. Re-run with --force "
                          "once you've inspected it, or recover the gap per SKILL.md step 2.")

    result = notewriter.write_note(paths, course, date, use_groq_signals=not args.no_groq_signals,
                                    digest_force=args.regenerate_digest, model=args.model)
    for w in result.warnings:
        print(f"   [note] {w}")
    print(f">> wrote {result.path}")
    print(f">> verify: {'CLEAN' if result.verified else 'FLAGGED -- unverified, see below'}")
    print(result.verify_output)

    notewriter.append_admin_and_questions(paths, course, date, result)

    print(">> rebuilding synthesis")
    syn_path, syn_warnings = synthesis.rebuild(paths, course, model=args.model)
    for w in syn_warnings:
        print(f"   [synthesis] {w}")
    print(f">> wrote {syn_path}")

    print("\n== report ==")
    print(f"course: {course.slug}  date: {date}  topic: {result.title}")
    print(f"exam signals caught: see {result.path}")
    print(f"verified: {result.verified}")
    if not result.verified:
        sys.exit(1)


def cmd_note(args):
    root = config.default_root()
    config.load_env(root)
    paths = _paths(args)
    course = config.resolve_course(root, args.course)
    datetime.date.fromisoformat(args.date)

    if args.dry_run:
        result = notewriter.write_note(paths, course, args.date, dry_run=True)
        for w in result.warnings:
            print(w)
        return

    result = notewriter.write_note(paths, course, args.date, use_groq_signals=not args.no_groq_signals,
                                    digest_force=args.regenerate_digest, model=args.model)
    for w in result.warnings:
        print(f"   [note] {w}")
    print(f">> wrote {result.path}")
    print(f">> verify: {'CLEAN' if result.verified else 'FLAGGED -- unverified'}")
    print(result.verify_output)
    if not result.verified:
        sys.exit(1)


def cmd_synthesis(args):
    root = config.default_root()
    config.load_env(root)
    paths = _paths(args)
    course = config.resolve_course(root, args.course)
    out_path, warnings = synthesis.rebuild(paths, course, dry_run=args.dry_run, model=args.model)
    for w in warnings:
        print(w)
    if out_path:
        print(f">> wrote {out_path}")


def cmd_verify(args):
    clean, out = scripts_bridge.verify_note(Path(args.note), Path(args.transcript))
    print(out)
    sys.exit(0 if clean else 1)


def cmd_status(args):
    root = config.default_root()
    extra = []
    if args.since:
        extra += ["--from", args.since]
    if args.all:
        extra += ["--all"]
    rc, out = scripts_bridge.term_coverage(root, extra)
    print(out)
    sys.exit(rc)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="classnotes")
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = dict(add_help=False)

    p_run = sub.add_parser("run", help="full pipeline: transcribe (if needed) -> note -> synthesis")
    p_run.add_argument("course")
    p_run.add_argument("input", nargs="?", help="media file, if a transcript doesn't already exist")
    p_run.add_argument("--date")
    p_run.add_argument("--lang")
    p_run.add_argument("--out-root")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--force", action="store_true", help="proceed past a density mismatch")
    p_run.add_argument("--no-groq-signals", action="store_true", help="skip Groq gloss of exam signals; use raw extracted lines")
    p_run.add_argument("--regenerate-digest", action="store_true")
    p_run.add_argument("--model")
    p_run.set_defaults(func=cmd_run)

    p_note = sub.add_parser("note", help="(re)write the note from an already-kept transcript")
    p_note.add_argument("course")
    p_note.add_argument("date")
    p_note.add_argument("--out-root")
    p_note.add_argument("--dry-run", action="store_true")
    p_note.add_argument("--no-groq-signals", action="store_true")
    p_note.add_argument("--regenerate-digest", action="store_true")
    p_note.add_argument("--model")
    p_note.set_defaults(func=cmd_note)

    p_syn = sub.add_parser("synthesis", help="rebuild SYNTHESIS.md from every lecture note")
    p_syn.add_argument("course")
    p_syn.add_argument("--out-root")
    p_syn.add_argument("--dry-run", action="store_true")
    p_syn.add_argument("--model")
    p_syn.set_defaults(func=cmd_synthesis)

    p_ver = sub.add_parser("verify", help="check a note against its transcript")
    p_ver.add_argument("note")
    p_ver.add_argument("transcript")
    p_ver.set_defaults(func=cmd_verify)

    p_stat = sub.add_parser("status", help="term coverage -- what's unprocessed")
    p_stat.add_argument("--from", dest="since")
    p_stat.add_argument("--all", action="store_true")
    p_stat.set_defaults(func=cmd_status)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except (config.ConfigError, groq_client.GroqError, scripts_bridge.ScriptError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
