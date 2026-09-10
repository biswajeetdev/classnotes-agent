"""Contract test: 'Synthesis is REBUILT, never appended.' (SKILL.md step 4 --
appending gives 100 files and no study material). Given an existing
SYNTHESIS.md, the pipeline must replace it: new content in, old unique
strings gone.

synthesis.rebuild() always calls Groq for the connective prose, so this is a
unit test importing classnotes.synthesis directly and monkeypatching
classnotes.groq_client.chat with a fake -- exactly the "pure unit tests with
fixtures and fakes, no network, no Groq calls" the task asked for. See
test_cli_contract.py's docstring for why the CLI-subprocess route can't be
used for this without a real GROQ_API_KEY (which this suite deliberately
never sets).

Skips cleanly until pybuild's feat/python-pipeline branch lands.
"""
from conftest import FIXTURES, require_classnotes

FAKE_SYNTHESIS_RESPONSE = """## Concept index
- *Cross validation* -- checking generalisation -> [2026-09-01](lectures/2026-09-01-cross-validation.md)

## How it fits together
Only one lecture so far; this section fills in as more are added.

## Likely exam questions
- What is cross validation used for? -> [2026-09-01](lectures/2026-09-01-cross-validation.md)

## Revised or contradicted
None yet.

## Thin ice
None yet.
"""


def _seeded_paths_and_course(classnotes_root, monkeypatch):
    from classnotes import config

    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    course = config.resolve_course(classnotes_root, "intro-statistics")
    paths = config.Paths(classnotes_root)

    old_synthesis = (FIXTURES / "sample_synthesis_old.md").read_text(encoding="utf-8")
    paths.synthesis(course.slug).write_text(old_synthesis, encoding="utf-8")
    lectures = paths.lectures_dir_write(course.slug)
    lectures.mkdir(parents=True, exist_ok=True)
    (lectures / "2026-09-01-cross-validation.md").write_text(
        (FIXTURES / "sample_note_clean.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return paths, course, old_synthesis


def test_synthesis_replaces_not_appends(classnotes_root, monkeypatch):
    require_classnotes()
    from classnotes import groq_client, synthesis

    paths, course, old_synthesis = _seeded_paths_and_course(classnotes_root, monkeypatch)
    monkeypatch.setattr(groq_client, "chat", lambda *a, **k: FAKE_SYNTHESIS_RESPONSE)

    out_path, warnings = synthesis.rebuild(paths, course)

    rebuilt = out_path.read_text(encoding="utf-8")
    assert "OLD_UNIQUE_MARKER_ZZZ" not in rebuilt, (
        "synthesis rebuild left stale content from the previous version -- "
        "it must be a full rewrite, not an append"
    )
    assert rebuilt != old_synthesis
    assert "Cross validation" in rebuilt


def test_synthesis_dry_run_does_not_touch_the_file(classnotes_root, monkeypatch):
    require_classnotes()
    from classnotes import groq_client, synthesis

    paths, course, old_synthesis = _seeded_paths_and_course(classnotes_root, monkeypatch)
    called = []
    monkeypatch.setattr(groq_client, "chat", lambda *a, **k: called.append(1) or FAKE_SYNTHESIS_RESPONSE)

    out_path, warnings = synthesis.rebuild(paths, course, dry_run=True)

    assert out_path is None
    assert not called, "dry-run must not call Groq at all"
    assert paths.synthesis(course.slug).read_text(encoding="utf-8") == old_synthesis


def test_rebuild_refuses_to_overwrite_when_the_model_returns_nothing(classnotes_root, monkeypatch):
    """A SYNTHESIS.md is a whole course's accumulated exam-prep value and rebuild
    is a full overwrite, so an unusable model reply must not be written over it.

    Measured 10 Sep 2026: GROQ_MODEL was a reasoning model, its `reasoning` field
    ate the completion budget, the API returned 200 with empty content, and this
    replaced an 18 KB synthesis with five "(not generated)" headings. The file
    must come out byte-identical instead."""
    require_classnotes()

    import pytest

    from classnotes import groq_client, synthesis

    paths, course, old_synthesis = _seeded_paths_and_course(classnotes_root, monkeypatch)
    monkeypatch.setattr(groq_client, "chat", lambda *a, **k: "")

    with pytest.raises(RuntimeError):
        synthesis.rebuild(paths, course)

    assert paths.synthesis(course.slug).read_text(encoding="utf-8") == old_synthesis, (
        "rebuild overwrote a real SYNTHESIS.md with an empty skeleton"
    )


def test_rebuild_refuses_a_partial_overwrite(classnotes_root, monkeypatch):
    """A truncated reply is the common case, not the rare one: the model runs out
    of budget partway down and the trailing sections go missing. Writing those as
    "(not generated)" over an existing synthesis loses real material, so a partial
    result must be refused too -- not just a wholly empty one."""
    require_classnotes()

    import pytest

    from classnotes import groq_client, synthesis

    paths, course, old_synthesis = _seeded_paths_and_course(classnotes_root, monkeypatch)
    truncated = FAKE_SYNTHESIS_RESPONSE.split("## Revised or contradicted")[0]
    monkeypatch.setattr(groq_client, "chat", lambda *a, **k: truncated)

    with pytest.raises(RuntimeError):
        synthesis.rebuild(paths, course)

    assert paths.synthesis(course.slug).read_text(encoding="utf-8") == old_synthesis


def test_chat_raises_instead_of_returning_empty_content(monkeypatch):
    """groq_client.chat() must never hand a caller "" as if it were a reply --
    that is the success-shaped failure that made the overwrite above possible.
    One retry at a bigger budget, then a loud GroqError."""
    require_classnotes()

    import json

    import pytest

    from classnotes import groq_client

    budgets = []

    class _Resp:
        headers: dict = {}  # chat() reads the rate-limit headers off every response

        def __init__(self, payload): self._p = payload
        def read(self): return json.dumps(self._p).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        budgets.append(json.loads(req.data)["max_completion_tokens"])
        return _Resp({"choices": [{"finish_reason": "length",
                                   "message": {"content": "", "reasoning": "thinking..."}}]})

    monkeypatch.setattr(groq_client.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(groq_client.GroqError):
        groq_client.chat("sys", "user", max_tokens=500, key="test-key")

    assert len(budgets) == 2, f"expected one retry at a larger budget, got {budgets}"
    assert budgets[1] > budgets[0]


def test_oversized_prompt_is_refused_before_it_is_sent(monkeypatch):
    """A prompt that leaves no room for a completion can never be served. Sending
    it anyway burned five retries and ~100s of sleep before dying "gave up after
    retries (rate limited)" -- a message naming the symptom and hiding the cause."""
    require_classnotes()

    import pytest

    from classnotes import groq_client

    sent = []
    monkeypatch.setattr(groq_client.urllib.request, "urlopen",
                        lambda *a, **k: sent.append(1))
    monkeypatch.setattr(groq_client, "TPM_LIMIT", 8000)

    with pytest.raises(groq_client.GroqError, match="no completion budget"):
        groq_client.chat("s" * 40_000, "u" * 40_000, key="test-key")
    assert not sent, "an unservable request must not reach the network at all"


def test_budget_is_sized_against_the_prompt(monkeypatch):
    """The completion budget has to shrink as the prompt grows, or a 6-lecture
    course asks for ~10,000 tokens against an 8,000-token/minute bucket."""
    require_classnotes()

    from classnotes import groq_client

    monkeypatch.setattr(groq_client, "TPM_LIMIT", 8000)
    monkeypatch.setattr(groq_client, "TPM_MARGIN", 400)

    small = groq_client.budget_for("x" * 400, want=6000)          # ~100 tokens
    large = groq_client.budget_for("x" * 4 * 4170, want=6000)     # ~4,170 tokens
    assert small == 6000, "a small prompt should get the full requested budget"
    assert large < 6000 and large + 4170 + 400 <= 8000, large


def test_waits_for_the_bucket_instead_of_firing_a_doomed_request(monkeypatch):
    """Groq reports what is left in the token bucket and when it refills. Honour
    that rather than sending a request that is going to 429."""
    require_classnotes()

    from classnotes import groq_client

    slept = []
    monkeypatch.setattr(groq_client.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(groq_client.time, "monotonic", lambda: 100.0)
    monkeypatch.setitem(groq_client._limits, "remaining", 200)
    monkeypatch.setitem(groq_client._limits, "reset", 30.0)
    monkeypatch.setitem(groq_client._limits, "at", 100.0)

    groq_client._wait_for_room(50)
    assert not slept, "a request that fits must not wait"

    groq_client._wait_for_room(5000)
    assert slept and 30 <= slept[0] <= 40, slept


def test_reset_header_durations_parse():
    require_classnotes()

    from classnotes import groq_client

    # "659ms" is the header Groq actually sends, and the ordered alternation
    # (h|m|s|ms) read it as 659 MINUTES -- which pinned every wait to the 90s cap
    # and turned a 20-second synthesis into a quarter of an hour.
    assert groq_client._parse_reset("659ms") == pytest_approx(0.659)
    assert groq_client._parse_reset("500ms") == pytest_approx(0.5)
    assert groq_client._parse_reset("2.857s") == pytest_approx(2.857)
    assert groq_client._parse_reset("1m30s") == pytest_approx(90.0)
    assert groq_client._parse_reset("1h39m21.6s") == pytest_approx(5961.6)
    assert groq_client._parse_reset(None) == 0.0


def pytest_approx(value):
    import pytest

    return pytest.approx(value)


def _http_error(groq_client, body, headers=None):
    import io
    import urllib.error

    return urllib.error.HTTPError(
        groq_client.API_URL, 429, "Too Many Requests", headers or {},
        io.BytesIO(body.encode()),
    )


def test_daily_limit_fails_fast_instead_of_retrying(monkeypatch):
    """TPD and TPM both answer 429, but only TPM is worth waiting out. At 199,067
    of 200,000 daily tokens used, the 13-second retry-after buys back ~1,000 tokens
    and a 6,000-token pass can never land -- so retrying just burns the clock and
    then reports "rate limited", naming neither cause. Measured 10 Sep 2026."""
    require_classnotes()

    import pytest

    from classnotes import groq_client

    body = ('{"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` '
            'in organization `org_x` service tier `on_demand` on tokens per day (TPD): '
            'Limit 200000, Used 199067, Requested 962. Please try again in 12.528s."}}')
    slept, tries = [], []

    def fake_urlopen(req, timeout=None):
        tries.append(1)
        raise _http_error(groq_client, body)

    monkeypatch.setattr(groq_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(groq_client.time, "sleep", lambda s: slept.append(s))

    with pytest.raises(groq_client.GroqError, match="daily token limit") as excinfo:
        groq_client.chat("s", "u", max_tokens=500, key="test-key")

    assert len(tries) == 1, "a daily-limit 429 must not be retried"
    assert not slept
    assert "199067 of 200000" in str(excinfo.value), (
        "the error must quote the real numbers, or the next reader re-derives them"
    )


def test_per_minute_limit_is_waited_out(monkeypatch):
    """The per-minute ceiling clears in seconds, so that one IS worth retrying."""
    require_classnotes()

    import json

    from classnotes import groq_client

    body = ('{"error":{"message":"Rate limit reached ... on tokens per minute (TPM): '
            'Limit 8000, Used 7900. Please try again in 3.5s."}}')
    slept, calls = [], []

    class _Resp:
        headers: dict = {}

        def read(self):
            return json.dumps({"choices": [{"finish_reason": "stop",
                                            "message": {"content": "ok"}}]}).encode()

        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(groq_client, body, {"retry-after": "3"})
        return _Resp()

    monkeypatch.setattr(groq_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(groq_client.time, "sleep", lambda s: slept.append(s))

    assert groq_client.chat("s", "u", max_tokens=500, key="test-key") == "ok"
    assert slept, "a per-minute 429 should wait and retry"
    assert len(calls) == 2
