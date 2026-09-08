"""classnotes -- pure-Python, no-agent pipeline for the classnotes workflow.

Groq does the language work (digest, note drafting, synthesis drafting).
Everything else -- transcript reuse, density checks, signal extraction,
verification gating, file assembly -- is deterministic Python that shells
out to the existing scripts/ tools rather than reimplementing them.

See scripts/../skill/SKILL.md for the spec this package implements.
"""

__version__ = "0.1.0"
