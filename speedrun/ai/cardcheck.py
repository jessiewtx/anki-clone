"""Speedrun LSAT: card-check for generated questions.

A question passes only if it is:
  - traceable : carries a named source,
  - single_skill : tagged with exactly one skill,
  - well_formed : 5 distinct choices with a valid answer index,
  - on_skill : its stem actually asks a Flaw question,
  - novel : not a near-duplicate of anything already in the study deck.

Novelty uses difflib ratio against every deck stimulus (no external deps).
"""

from __future__ import annotations

import json
import os
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
NOVELTY_MAX_SIM = 0.6
FLAW_STEM_HINTS = ("vulnerable to criticism", "flawed", "flaw", "questionable in that")

CRITERIA = ["traceable", "single_skill", "well_formed", "on_skill", "novel"]


def deck_stimuli() -> list[str]:
    deck = json.load(open(SEED, encoding="utf-8"))
    out = []
    for c in deck.get("cards", []):
        for field in ("stimulus", "front"):
            if c.get(field):
                out.append(c[field].lower())
    return out


def _max_similarity(text: str, corpus: list[str]) -> float:
    t = (text or "").lower()
    return max((SequenceMatcher(None, t, other).ratio() for other in corpus), default=0.0)


def check_question(q: dict, corpus: list[str]) -> dict:
    choices = q.get("choices", [])
    stem = (q.get("question") or "").lower()
    checks = {
        "traceable": bool(q.get("source") and q["source"].get("name")),
        "single_skill": bool(q.get("skill")),
        "well_formed": (
            len(choices) == 5
            and len(set(choices)) == 5
            and isinstance(q.get("answerIndex"), int)
            and 0 <= q["answerIndex"] < len(choices)
        ),
        "on_skill": q.get("skill") == "lr_flaw" and any(h in stem for h in FLAW_STEM_HINTS),
        "novel": _max_similarity(q.get("stimulus", ""), corpus) < NOVELTY_MAX_SIM,
    }
    checks["pass"] = all(checks[c] for c in CRITERIA)
    checks["similarity"] = round(_max_similarity(q.get("stimulus", ""), corpus), 2)
    return checks
