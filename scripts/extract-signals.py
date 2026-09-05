#!/usr/bin/env python3
"""Pull exam-signal lines out of a transcript, verbatim and losslessly.

    extract-signals.py <transcript.txt> [>> digest.md]

Measured 22 Aug: the Groq digest fabricated nothing, but it DROPPED the two highest
value items in the lecture -- "according to the syllabus ... that's why we need to read
it" and "we can change the model, but we cannot change the data". A summariser
optimises for topic coverage; it has no notion that one sentence is worth more than a
paragraph. Exam signals are exactly that kind of sentence.

So this does not summarise. It greps, and it keeps the professor's words untouched.
Cheap, deterministic, and it cannot lose what it matches.
"""
import re, sys
from collections import Counter

# Phrases that mark something as assessable, in the English these lecturers actually use.
SIGNAL = re.compile(r"""(
    exam | syllabus | test | quiz | marks?\b | assignment | submit
  | important | remember | note\s+(?:this|that|down) | keep\s+in\s+mind
  | must\s+(?:know|read|remember) | make\s+sure
  | (?:will|would|can)\s+(?:come|be\s+asked)
  | i\s+want\s+you\s+to | you\s+(?:have|need)\s+to
  # Emphasis carrying no signal WORD. Measured 22 Aug: "we can change the model, but we
  # can't change the data" was the most repeated line of the lecture and matched none of
  # the patterns above, because superlatives and absolutes are how these lecturers stress
  # a point -- not by saying "this is important".
  | biggest | most\s+(?:important|relevant|reliable|critical)
  | only\s+difference | that'?s\s+why | key\s+(?:point|thing|difference)
  | (?:can'?t|cannot|never)\s+(?:change|do|say|be)
  | 100\s*(?:%|percent)
  | परीक्षा | महत्वपूर्ण | याद\s+रख | ज़रूरी
)""", re.I | re.X)

NOISE = re.compile(r"^\s*(okay|yeah|yes|thank you|so|um+|uh+|hmm|\*[^*]+\*)[\s.]*$", re.I)

def main():
    lines = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    lines = [l for l in lines if not NOISE.match(l)]

    hits = [l for l in lines if SIGNAL.search(l)]

    # A line the professor repeats is emphasis by definition, whether or not it carries
    # a signal word. Catch those too.
    norm = lambda s: re.sub(r"[^a-z ]", "", s.lower()).strip()
    counts = Counter(norm(l) for l in lines if 5 <= len(l.split()) <= 30)
    repeated = {k for k, v in counts.items() if v >= 3 and k}
    repeats = []
    seen = set()
    for l in lines:
        n = norm(l)
        if n in repeated and n not in seen:
            seen.add(n); repeats.append((counts[n], l))

    print("## Exam signals (verbatim — extracted, not summarised)")
    if hits:
        for l in dict.fromkeys(hits):
            print(f"- {l}")
    else:
        print("- none matched")
    if repeats:
        print("\n## Repeated lines (emphasis by repetition)")
        for c, l in sorted(repeats, reverse=True)[:15]:
            print(f"- ({c}x) {l}")

if __name__ == "__main__":
    main()
