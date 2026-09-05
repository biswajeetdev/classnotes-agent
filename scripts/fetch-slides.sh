#!/usr/bin/env bash
# Get the professor's uploaded slides out of Moodle and into the course folder.
#
#   fetch-slides.sh <course-slug>          # open that course's Lecture Notes in Chrome
#   fetch-slides.sh <course-slug> collect  # file anything new from ~/Downloads
#
# Moodle needs an authenticated session, and the file itself sits behind that login.
# Rather than handle your credentials or scrape cookies, this opens the page in the
# Chrome you are already signed into; you click the files; `collect` then files them.
#
# Uploaded slides beat screen capture every time: real text, nothing clipped, and they
# include slides the professor skipped past too quickly to read.

set -uo pipefail
ROOT="$HOME/class-notes"
SLUG="${1:?usage: fetch-slides.sh <course-slug> [collect]}"
MODE="${2:-open}"

MOODLE_ID=$(python3 - "$SLUG" <<'PY'
import sys, os
slug=sys.argv[1]; cur=None
for ln in open(os.path.expanduser("~/class-notes/courses.yaml")):
    s=ln.strip()
    if s.startswith("- slug:"): cur=s.split(":",1)[1].strip()
    elif s.startswith("moodle_id:") and cur==slug:
        print(s.split(":",1)[1].strip()); break
PY
)
[ -n "$MOODLE_ID" ] || { echo "error: no moodle_id for '$SLUG' in courses.yaml" >&2; exit 1; }
DEST="$ROOT/$SLUG/slides"; mkdir -p "$DEST"

if [ "$MODE" = "open" ]; then
  URL="${MOODLE_BASE:-https://moodle.example.edu/moodle}/course/view.php?id=$MOODLE_ID"
  echo ">> opening $SLUG (Moodle id $MOODLE_ID)"
  echo ">> go to the 'Lecture Notes' section and download the slide files"
  echo ">> then run:  $0 $SLUG collect"
  open -a "Google Chrome" "$URL"
  exit 0
fi

# collect: anything slide-shaped that landed in Downloads in the last 2 hours
FOUND=0
while IFS= read -r f; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  case "$base" in
    *.pdf|*.ppt|*.pptx|*.PDF|*.PPT|*.PPTX) ;;
    *) continue ;;
  esac
  if [ -e "$DEST/$base" ]; then echo "  already have: $base"; continue; fi
  mv "$f" "$DEST/$base" && { echo "  filed: $base"; FOUND=$((FOUND+1)); }
done < <(find "$HOME/Downloads" -maxdepth 1 -type f -newermt '-2 hours' 2>/dev/null)

if [ "$FOUND" -eq 0 ]; then
  echo "  nothing new found in ~/Downloads from the last 2 hours."
  echo "  Download the files from Moodle first, then re-run with 'collect'."
else
  echo ">> $FOUND file(s) -> $DEST"
  echo ">> now run /classnotes; it will read these instead of screen captures"
fi
ls -la "$DEST" 2>/dev/null | grep -viE '^total|^d' | awk '{printf "  %8.0f KB  %s\n", $5/1024, $NF}'
