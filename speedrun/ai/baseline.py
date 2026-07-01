"""Speedrun LSAT: the naive baseline the generator must beat.

A keyword/retrieval "generator": given the target skill, it just returns existing
practice questions from the deck. They're valid questions, but they are NOT novel
(they already exist in the study deck), so the card-check's novelty test rejects
them. This is the honest bar: real generation must produce *new* valid questions,
not recycle the bank.
"""

from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
SKILL_TAG = "lsat::lr::flaw"


def _resolve_source(raw, sources: dict) -> dict:
    if isinstance(raw, dict):
        return raw
    src = sources.get(raw, {}) if isinstance(raw, str) else {}
    return {"name": src.get("name", str(raw)), "url": src.get("url", "")}


class KeywordBaseline:
    name = "baseline"

    def __init__(self) -> None:
        deck = json.load(open(SEED, encoding="utf-8"))
        sources = deck.get("sources", {})
        cards = deck.get("cards", [])
        pool = [
            c for c in cards
            if c.get("type") == "practice" and SKILL_TAG in c.get("tags", [])
        ]
        if not pool:  # fall back to any flaw-family practice item
            pool = [
                c for c in cards
                if c.get("type") == "practice"
                and any("flaw" in t for t in c.get("tags", []))
            ]
        self.pool = [
            {
                "id": f"baseline_{c['id']}",
                "skill": "lr_flaw",
                "stimulus": c.get("stimulus", ""),
                "question": c.get("question", ""),
                "choices": c.get("choices", []),
                "answerIndex": c.get("answerIndex", 0),
                "explanation": c.get("explanation", ""),
                "origin": "baseline-retrieval",
                "source": _resolve_source(c.get("source"), sources),
            }
            for c in pool
        ]

    def generate(self, n: int) -> list[dict]:
        if not self.pool:
            return []
        out = []
        i = 0
        while len(out) < n:
            out.append(self.pool[i % len(self.pool)])
            i += 1
        return out
