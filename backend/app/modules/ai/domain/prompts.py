"""Prompt rules shared by the AI features and the eval set (WP-038). Pure."""

# Writing help's rules: facts from the record only, nothing promised or invented. `make ai-eval`
# checks a model keeps them (the invented-commitment cases).
RULES = (
    "Use only facts written in the record below. Never promise anything, and never add "
    "dates, times, names, numbers, prices or next steps that are not in it; if something is "
    "not known, leave it out. Do not say what will happen next, when it will be fixed, or "
    "that it will not happen again, unless the record says so. Placeholders such as "
    "⟦PERSON_1⟧ stand for real values: keep them exactly. Answer with the text only: no "
    "preamble, no notes about what you did."
)
