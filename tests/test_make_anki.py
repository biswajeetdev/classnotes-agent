"""SYNTHESIS.md -> Anki cards.

The regression that matters here is the numbering format. Notes write exam
questions two ways -- `**1. Question**` and `1. **Question**` -- and a parser that
knows only one produces zero exam cards for the other courses while reporting
success. That looks exactly like a synthesis with no questions in it, so it is
the kind of miss nobody notices until revision week.
"""
from conftest import import_script

anki = import_script("make-anki.py")

SYNTH = """# A course — Exam Synthesis

## Concept index

| Concept | One line | Best note |
|---|---|---|
| **Nested-set model** | Behaviour ⊃ OB ⊃ HR | [26 Aug](lectures/a.md) |
| **Culture outlasts churn** | ~90% turn over; culture does not | [26 Aug](lectures/a.md) |

## Likely exam questions
*Ranked by density.*

**1. Explain the Hawthorne studies.**
Two sessions, closed with a consensus check. See [5 Sep](lectures/b.md).

**2. Skinner / Bandura / Vroom.** Promised for the final exam.

## Thin ice
Nothing here should become a card.
"""

SYNTH_OUTSIDE = """# Another course

## Likely exam questions

1. **Compute accuracy from a confusion matrix.** He flagged the cell order as
   "very important" and worked the numbers live. [19 Sep](lectures/c.md)

2. **Define bias and variance.** Asked twice.
"""


def test_concept_rows_become_cards():
    cards = anki.concept_cards(anki.sections(SYNTH)["concept index"])
    fronts = [f for f, _ in cards]
    assert "<b>Nested-set model</b>" in fronts
    assert len(cards) == 2, "header and |---| rule must not become cards"


def test_concept_card_carries_its_source():
    cards = dict(anki.concept_cards(anki.sections(SYNTH)["concept index"]))
    assert "26 Aug" in cards["<b>Nested-set model</b>"]


def test_exam_questions_number_inside_the_bold():
    cards = anki.exam_cards(anki.sections(SYNTH)["likely exam questions"])
    assert len(cards) == 2
    assert cards[0][0] == "Explain the Hawthorne studies."
    assert "consensus check" in cards[0][1]


def test_exam_questions_number_outside_the_bold():
    """The format five of six courses actually use."""
    cards = anki.exam_cards(anki.sections(SYNTH_OUTSIDE)["likely exam questions"])
    assert len(cards) == 2, "numbering outside the bold must still parse"
    assert cards[0][0] == "Compute accuracy from a confusion matrix."
    assert "confusion" in cards[0][0]


def test_other_sections_do_not_become_cards():
    secs = anki.sections(SYNTH)
    assert "thin ice" in secs
    assert "concept index" in secs and "likely exam questions" in secs


def test_markdown_links_lose_the_url_but_keep_the_text():
    assert anki.to_html("see [26 Aug](lectures/very/long/path.md)") == "see 26 Aug"


def test_tabs_never_survive_into_a_field():
    """A stray tab would split one card into two fields and corrupt the import."""
    assert "\t" not in anki.to_html("a\tb")


def test_bold_and_italic_become_html():
    assert anki.to_html("**x** and *y*") == "<b>x</b> and <i>y</i>"
