"""Generic Groq chat call with the same rate-limit pacing digest.py uses.

Free tier is 8,000 tokens/minute (throughput, not context -- the model itself
takes 131k context). digest.py already solved the pacing problem for its own
chunked digest pass; this module provides the same call()/retry/backoff shape
for the OTHER Groq calls this package adds (note-body drafting, signal
glossing, synthesis drafting) so they don't each reinvent it.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

API_URL = "https://api.groq.com/openai/v1/chat/completions"


def default_model() -> str:
    # Read at call time, not import time -- config.load_env() populates
    # GROQ_MODEL from ~/class-notes/.env only once main() has run, which is
    # after this module is first imported.
    return os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Groq sits behind Cloudflare, which rejects Python's default User-Agent with a
# 403 that looks exactly like a bad API key. It is not -- see digest.py.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class GroqError(Exception):
    pass


def _request(payload: dict, key: str) -> urllib.request.Request:
    return urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": _UA})


def require_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise GroqError("GROQ_API_KEY not set. Put it in ~/class-notes/.env")
    return key


def chat(system: str, user: str, *, model: str | None = None, temperature: float = 0.1,
         max_tokens: int = 2000, retries: int = 5, key: str | None = None) -> str:
    key = key or require_key()
    model = model or default_model()
    payload = {
        "model": model,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    req = _request(payload, key)
    bumped = False
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
            choice = data["choices"][0]
            content = (choice["message"].get("content") or "").strip()
            truncated = choice.get("finish_reason") == "length"
            if content and not truncated:
                return content
            # finish_reason="length" means the reply was cut off mid-thought, so
            # even a non-empty content is a partial answer -- for the synthesis
            # pass that arrives as prose with the section headings missing, which
            # is indistinguishable from "the model returned nothing usable".
            # A reasoning model (GROQ_MODEL=openai/gpt-oss-120b is one) spends the
            # completion budget on its `reasoning` field first. If the budget runs
            # out there, the API returns HTTP 200 with finish_reason="length" and
            # an EMPTY content -- a success-shaped total failure. Returning "" here
            # let synthesis.rebuild() overwrite a real SYNTHESIS.md with an empty
            # skeleton. Give it one bigger budget, then fail loudly.
            if truncated and not bumped:
                bumped = True
                payload["max_completion_tokens"] = min(max_tokens * 4, 16000)
                req = _request(payload, key)
                continue
            if content:
                return content  # truncated twice; a partial reply beats nothing
            raise GroqError(
                f"Groq returned no content (finish_reason="
                f"{choice.get('finish_reason')!r}, model={model}). "
                f"Reasoning models need a larger max_tokens than {max_tokens}."
            )
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            if e.code in (429, 413):
                m = re.search(r"try again in ([\d.]+)s", raw)
                wait = min(float(m.group(1)) + 2, 90) if m else 20 * (attempt + 1)
                time.sleep(wait)
                continue
            raise GroqError(f"Groq HTTP {e.code}: {raw[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                raise GroqError(f"Groq request failed: {e}") from e
            time.sleep(10 * (attempt + 1))
    raise GroqError("Groq: gave up after retries (rate limited)")


def chunk_words(text: str, size: int = 2500) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def pace(seconds: float | None = None):
    """Sleep between paced calls -- stays under the 8k TPM free-tier cap."""
    time.sleep(seconds if seconds is not None else float(os.environ.get("GROQ_PACE_SEC", "35")))
