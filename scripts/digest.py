#!/usr/bin/env python3
"""Condense a raw lecture transcript into a structured digest, using Groq.

    digest.py <transcript.txt> [out.md]

Why: reading a 10,000-word transcript is the expensive part of writing a note, and it
is also the most mechanical — finding what was said and grouping it. That is worth
offloading. Judgement (what matters, what the exam will ask, how it connects to prior
lectures) stays with the model writing the note.

SAFETY: a digest is lossy by construction, so the note built from it could drift from
what was actually said. That is why `verify-notes.py` checks the finished note against
the FULL original transcript, never against this digest. Keep that order.
"""
import json, os, re, sys, time, urllib.error, urllib.request

def load_env():
    # Resolve .env from the configured root, not a hardcoded $HOME. transcribe.sh
    # already took this fix for the model files; digest.py kept reading the real
    # ~/class-notes/.env even when CLASSNOTES_ROOT pointed somewhere else, so the
    # test suite picked up the user's live API key and spent real quota against it
    # -- three `run` tests timed out at 30s once the default model was one that
    # actually answers.
    root = os.environ.get("CLASSNOTES_ROOT") or os.path.expanduser("~/class-notes")
    p = os.path.join(root, ".env")
    if os.path.exists(p):
        for ln in open(p):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

PROMPT = """You are condensing a university lecture transcript for a student's exam notes.

Rules:
- Report ONLY what is in the transcript. Never add facts, figures, names or examples.
- Keep numbers, names and technical terms EXACTLY as they appear, even if they look
  garbled by speech recognition. Do not silently correct them.
- Preserve direct quotes verbatim when the professor emphasises something.
- If something is unclear, write [unclear] rather than guessing.

Produce:
## Topics
Ordered list of what was covered, with a one-line summary each.
## Key statements
Substantive claims, definitions, formulas, and worked examples. Quote where exact wording matters.
## Emphasis
Anything the professor repeated, slowed down for, or explicitly flagged as important or exam material. Quote it.
## Q&A
Each student question and the answer given.
## Admin and assignments
Any task, deadline, schedule change, or material promised. Quote the exact instruction.
"""

def call(chunk, key, model):
    body = json.dumps({
        "model": model,
        "temperature": 0.1, "max_completion_tokens": 1500,
        "messages": [{"role": "system", "content": PROMPT},
                     {"role": "user", "content": chunk}],
    }).encode()
    # Groq sits behind Cloudflare, which rejects Python's default User-Agent with
    # "403 error code: 1010" -- which looks exactly like a bad API key. It is not.
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

def main():
    load_env()
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        print("error: GROQ_API_KEY not set. Put it in ~/class-notes/.env", file=sys.stderr)
        return 2
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")  # llama-3.3 is decommissioned
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.replace(".txt", "-digest.md")
    text = open(src, encoding="utf-8").read()

    words = text.split()
    # The model's context is 131k, but the FREE TIER caps at 8,000 tokens per minute --
    # so the limit is throughput, not context. ~2,500 words in plus ~1,200 out keeps a
    # single call under the cap; the pacing below keeps the sequence under it too.
    size = int(os.environ.get("DIGEST_CHUNK_WORDS", "2500"))
    chunks = [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
    print(f"  {len(words)} words -> {len(chunks)} call(s) to {model}")

    out = []
    for i, c in enumerate(chunks, 1):
        for attempt in range(5):
            try:
                out.append(call(c, key, model))
                print(f"  part {i}/{len(chunks)} ok")
                break
            except urllib.error.HTTPError as e:
                raw = e.read().decode(errors="replace")
                if e.code in (429, 413):
                    # honour the wait the API asks for; guessing shorter just fails again
                    m = re.search(r"try again in ([\d.]+)s", raw)
                    wait = min(float(m.group(1)) + 2, 90) if m else 20 * (attempt + 1)
                    print(f"  part {i}: rate limited, waiting {wait:.0f}s")
                    time.sleep(wait)
                    continue
                print(f"  part {i} FAILED: {e.code} {raw[:200]}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"  part {i} FAILED: {e}", file=sys.stderr)
                return 1
        else:
            print(f"  part {i} gave up after retries", file=sys.stderr)
            return 1
        if i < len(chunks):
            time.sleep(float(os.environ.get("DIGEST_PACE_SEC", "35")))   # stay under 8k TPM

    header = (f"<!-- digest of {os.path.basename(src)} via {model}. "
              f"LOSSY — verify the finished note against the full transcript, not this. -->\n\n")
    open(dst, "w", encoding="utf-8").write(header + "\n\n---\n\n".join(out))
    print(f"  wrote {dst} ({len(' '.join(out).split())} words, "
          f"{100 - int(len(' '.join(out).split()) / max(len(words),1) * 100)}% smaller)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
