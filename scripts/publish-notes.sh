#!/usr/bin/env bash
# Publish notes as PDFs to $PUBLISH_DIR/<Course Name>/  (default ~/Desktop/Courses)
#
#   publish-notes.sh [course-slug]     # omit to publish every course
#
# ~/class-notes stays the working directory (transcripts, audio, markdown).
# The Desktop tree is the readable copy — PDFs only, named so they sort by date.

set -uo pipefail
ROOT="$HOME/class-notes"
DEST="${PUBLISH_DIR:-$HOME/Desktop/Courses}"
ONLY="${1:-}"

name_for() {  # slug -> the course's real name, from courses.yaml
  python3 - "$1" <<'PY'
import sys,re
slug=sys.argv[1]; cur=None; code=None
for ln in open(f"{__import__('os').path.expanduser('~')}/class-notes/courses.yaml"):
    s=ln.strip()
    if s.startswith("- slug:"): cur=s.split(":",1)[1].strip()
    elif s.startswith("code:") and cur==slug: code=s.split(":",1)[1].strip()
    elif s.startswith("name:") and cur==slug:
        print(f"{code} {s.split(':',1)[1].strip()}".replace("/","-")); break
else: print(slug)
PY
}

for dir in "$ROOT"/*/; do
  slug=$(basename "$dir")
  case "$slug" in scripts|models|_*) continue ;; esac
  [ -n "$ONLY" ] && [ "$slug" != "$ONLY" ] && continue
  ls "$dir"lectures/*.md >/dev/null 2>&1 || continue

  pretty=$(name_for "$slug")
  out="$DEST/$pretty"
  mkdir -p "$out"
  echo "== $pretty"

  for md in "$dir"lectures/*.md; do
    base=$(basename "$md" .md)
    python3 "$ROOT/scripts/md2pdf.py" "$md" "$out/$base.pdf" "$base"
  done
  # Synthesis first alphabetically, so it is the file you open
  [ -f "$dir/SYNTHESIS.md" ] && python3 "$ROOT/scripts/md2pdf.py" "$dir/SYNTHESIS.md" \
      "$out/00 - EXAM SYNTHESIS.pdf" "$pretty — Exam Synthesis"
  # Assignments get their own file and sort second — deadlines are the one thing
  # you must not have to hunt for inside a lecture note.
  [ -f "$dir/ASSIGNMENTS.md" ] && python3 "$ROOT/scripts/md2pdf.py" "$dir/ASSIGNMENTS.md" \
      "$out/01 - ASSIGNMENTS.pdf" "$pretty — Assignments"
  [ -f "$dir/QUESTIONS.md" ] && python3 "$ROOT/scripts/md2pdf.py" "$dir/QUESTIONS.md" \
      "$out/02 - Open Questions.pdf" "$pretty — Open Questions"
  # slides the professor uploaded, copied through as-is
  if ls "$dir"slides/*.pdf "$dir"slides/*.ppt* >/dev/null 2>&1; then
    mkdir -p "$out/Slides"; cp "$dir"slides/*.pdf "$dir"slides/*.ppt* "$out/Slides/" 2>/dev/null
    echo "  copied $(ls "$out/Slides" | wc -l | tr -d ' ') slide file(s)"
  fi
done
echo
echo "published to: $DEST"
