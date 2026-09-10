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

# Free tier is 8,000 tokens/minute across prompt + completion, measured from the
# x-ratelimit-limit-tokens header. Billing is by ACTUAL usage, not by the budget
# asked for: a request with max_completion_tokens=30000 is served happily. So a
# request fails only when what it really consumes exceeds what the bucket holds,
# and the fix is to size the completion budget against the prompt rather than to
# pick a smaller constant.
TPM_LIMIT = int(os.environ.get("GROQ_TPM_LIMIT", "8000"))
TPM_CEILING = int(os.environ.get("GROQ_MAX_COMPLETION_TOKENS", "6000"))
TPM_MARGIN = 400  # tokeniser slack + the response envelope

# Rate-limit state from the last response's headers. Groq reports what is left in
# the bucket and when it refills, which beats guessing at a local token bucket.
_limits: dict = {"remaining": None, "reset": 0.0, "at": 0.0}


def estimate_tokens(text: str) -> int:
    """~4 chars/token. Deliberately crude: it only has to be right enough to keep
    a request inside the bucket, and TPM_MARGIN absorbs the error."""
    return len(text) // 4 + 1


def budget_for(prompt: str, want: int = TPM_CEILING) -> int:
    """The largest completion budget that can still fit beside this prompt.

    Without this, synthesis asked for 6,000 completion tokens next to a 4,170-token
    prompt on a 6-lecture course: ~10,000 against an 8,000 bucket, which can never
    be served no matter how long you wait. It burned five retries and died
    "gave up after retries (rate limited)", a message that names the symptom and
    hides the cause."""
    room = TPM_LIMIT - estimate_tokens(prompt) - TPM_MARGIN
    return max(512, min(want, room))


def _parse_reset(value: str | None) -> float:
    """Groq spells these "2.857s", "1m30s", "1h39m21.6s"."""
    if not value:
        return 0.0
    total, seen = 0.0, False
    # "ms" must precede "m": Python's alternation is ordered, so (h|m|s|ms) reads
    # "659ms" as 659 MINUTES and every subsequent wait pins to the 90s cap.
    for amount, unit in re.findall(r"([\d.]+)\s*(ms|h|m|s)", value):
        seen = True
        total += float(amount) * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[unit]
    if seen:
        return total
    try:
        return float(value)
    except ValueError:
        return 0.0


def _note_limits(headers) -> None:
    remaining = headers.get("x-ratelimit-remaining-tokens")
    if remaining is None:
        return
    try:
        _limits["remaining"] = int(float(remaining))
    except (TypeError, ValueError):
        return
    _limits["reset"] = _parse_reset(headers.get("x-ratelimit-reset-tokens"))
    _limits["at"] = time.monotonic()


def _wait_for_room(need: int) -> None:
    """Sleep until the bucket can hold `need`, rather than firing a doomed request
    and reading the 429 afterwards."""
    remaining = _limits["remaining"]
    if remaining is None or need <= remaining:
        return
    waited = time.monotonic() - _limits["at"]
    sleep_for = _limits["reset"] - waited
    if sleep_for > 0:
        time.sleep(min(sleep_for + 1, 90))
    _limits["remaining"] = None  # stale after the wait; the next response refreshes it


def default_model() -> str:
    # Read at call time, not import time -- config.load_env() populates
    # GROQ_MODEL from ~/class-notes/.env only once main() has run, which is
    # after this module is first imported.
    # llama-3.3-70b-versatile was the original default and has since been
    # decommissioned -- Groq now answers HTTP 404 "does not exist or you do not
    # have access to it" for it, which reads like a permissions problem rather
    # than a retired model. gpt-oss-120b is a reasoning model; chat() handles
    # the truncation that implies.
    return os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

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
    # Clamp the budget against the prompt up front. An oversized budget IS served
    # (billing is by actual usage), but a reasoning model will spend whatever it is
    # given, so the request that comes back is the one that blows the bucket.
    payload = {
        "model": model,
        "temperature": temperature,
        "max_completion_tokens": budget_for(system + user, want=max_tokens),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    prompt_tokens = estimate_tokens(system) + estimate_tokens(user)
    if prompt_tokens + TPM_MARGIN >= TPM_LIMIT:
        raise GroqError(
            f"prompt is ~{prompt_tokens} tokens against a {TPM_LIMIT}-token/minute "
            "limit; no completion budget can fit beside it. Send less input."
        )
    req = _request(payload, key)
    bumped = False
    for attempt in range(retries):
        try:
            _wait_for_room(prompt_tokens + payload["max_completion_tokens"])
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
                _note_limits(r.headers)
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
                # Bounded by the free tier's 8,000 tokens/minute, which counts the
                # prompt too: a blind 4x of a 3,000-token budget asks for 12,000 and
                # can never fit, so every retry 429s and the call dies "rate limited"
                # instead of returning the answer the smaller budget nearly had.
                bumped = True
                payload["max_completion_tokens"] = budget_for(
                    system + user, want=max_tokens * 2)
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
            _note_limits(e.headers)
            if e.code in (429, 413):
                # Two different ceilings answer 429. The per-minute one (TPM) clears
                # in seconds and is worth waiting out. The per-DAY one (TPD, 200,000
                # on the free tier) does not: at 199,067 used, a 13-second wait buys
                # back ~1,000 tokens, so a 6,000-token synthesis pass can never
                # complete and the retries just burn the clock before reporting a
                # generic "rate limited" that names neither cause.
                #
                # Note the per-minute headers stay healthy while TPD is exhausted --
                # x-ratelimit-remaining-tokens read 8000 against this very 429 -- so
                # the body is the only place the real limit is named.
                if "per day" in raw or "TPD" in raw:
                    used = re.search(r"Limit (\d+), Used (\d+)", raw)
                    detail = f" ({used.group(2)} of {used.group(1)} used)" if used else ""
                    raise GroqError(
                        f"Groq daily token limit reached{detail}. This resets on a "
                        "24-hour cycle; waiting will not help today. Use a smaller "
                        "model, or upgrade the tier."
                    ) from e
                after = e.headers.get("retry-after")
                m = re.search(r"try again in ([\d.]+)s", raw)
                if after:
                    wait = min(float(after) + 2, 90)
                elif m:
                    wait = min(float(m.group(1)) + 2, 90)
                else:
                    wait = 20 * (attempt + 1)
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
