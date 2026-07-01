"""Speedrun LSAT: LR question generators.

Two implementations behind one interface:
- RulesGenerator: builds NEW, valid "Flaw" questions by instantiating cited flaw
  definitions into fresh stimuli. Needs no API key -> this is the AI-OFF path.
- LLMGenerator: same interface, drop in a real model later. Left as a stub so the
  wiring point is obvious and the app never depends on a model being present.

Each generated question traces to a named, free, human-written source.
"""

from __future__ import annotations

import json
import os
import random
from typing import Protocol

HERE = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE = os.path.join(HERE, "knowledge.json")


def _load() -> dict:
    with open(KNOWLEDGE, encoding="utf-8") as fh:
        return json.load(fh)


class Generator(Protocol):
    name: str

    def generate(self, n: int) -> list[dict]:
        ...


def _stimulus(flaw: dict, topic) -> str:
    kind = flaw.get("kind")
    if kind == "conditional_affirm":
        return f"If {topic['p']}, then {topic['q']}. {topic['q_obs']}. Therefore, {topic['p_conc']}."
    if kind == "conditional_deny":
        return f"If {topic['p']}, then {topic['q']}. {topic['p_neg']}. Therefore, {topic['q_neg']}."
    # causal / sample topics are already complete stimuli
    return topic


class RulesGenerator:
    """AI-off generator: valid, source-cited Flaw questions from templates."""

    name = "rules"

    def __init__(self, seed: int = 7) -> None:
        self.k = _load()
        self.rng = random.Random(seed)
        self.stem = self.k["stem"]
        self.flaws = self.k["flaws"]
        self._by_kind = {
            "conditional_affirm": self.k["topics"]["conditional"],
            "conditional_deny": self.k["topics"]["conditional"],
            "causal": self.k["topics"]["causal"],
            "sample": self.k["topics"]["sample"],
        }

    def _make(self, flaw: dict, topic, idx: int) -> dict:
        correct = flaw["answer"]
        others = [f["answer"] for f in self.flaws if f["id"] != flaw["id"]]
        distractors = self.rng.sample(others, 4)
        choices = distractors + [correct]
        self.rng.shuffle(choices)
        return {
            "id": f"gen_flaw_{flaw['id']}_{idx}",
            "skill": self.k["skill"],
            "stimulus": _stimulus(flaw, topic),
            "question": self.stem,
            "choices": choices,
            "answerIndex": choices.index(correct),
            "explanation": (
                f"This argument commits {flaw['name']}: it {flaw['answer']}. "
                f"(Source: {flaw['source']['name']})"
            ),
            "origin": "generated-rules",
            "source": flaw["source"],
        }

    def generate(self, n: int) -> list[dict]:
        out: list[dict] = []
        idx = 0
        for flaw in self.flaws:
            topics = self._by_kind.get(flaw.get("kind"))
            if not topics:
                continue  # flaw is a distractor-only entry (no template)
            for topic in topics:
                out.append(self._make(flaw, topic, idx))
                idx += 1
                if len(out) >= n:
                    return out
        return out


class LLMGenerator:
    """Drop-in slot for a real model. Enable by implementing `_draft` with your
    provider of choice; the rest of the pipeline (card-check, eval, app) is
    unchanged. Kept as a stub so the app is AI-off safe by default."""

    name = "llm"

    def __init__(self, model: object | None = None) -> None:
        self.model = model

    def generate(self, n: int) -> list[dict]:
        raise NotImplementedError(
            "No model configured. Rules-based generation is the default; wire an LLM "
            "here later (same return shape as RulesGenerator.generate)."
        )
