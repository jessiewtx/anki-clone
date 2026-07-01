"""Quality + variety checks for the LR practice bank (Speedrun LSAT).

Run after each generation batch:
    out/pyenv/bin/python speedrun/scripts/check_bank.py

For every elimination-tagged question it verifies:
  - exactly 5 distinct answer choices and a valid answer index,
  - choiceTraps aligned (the answer is null, every wrong choice has a valid trap),
  - a source is present.
It also flags near-duplicate stimuli (so the bank stays varied) and prints a
variety report: counts per LR skill, per trap type, and per difficulty.
Exit code is nonzero if any structural problem is found.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
DUP_THRESHOLD = 0.80
TRAPS = {
    "out_of_scope", "too_strong", "reversal", "half_right", "correlation_causation",
    "could_be_true", "restates_premise", "plausible_unsupported", "shifted_subject",
}


def lr_skill(card: dict) -> str | None:
    for t in card.get("tags", []):
        if t.startswith("lsat::lr::"):
            return t.split("::")[-1]
    return None


def main() -> int:
    d = json.load(open(SEED, encoding="utf-8"))
    practice = [c for c in d["cards"] if c.get("type") == "practice"]
    elim = [c for c in practice if "lsat::mode::elimination" in c.get("tags", [])]

    problems: list[str] = []
    for c in elim:
        cid = c["id"]
        ch = c.get("choices", [])
        ai = c.get("answerIndex")
        tr = c.get("choiceTraps")
        if len(ch) != 5 or len(set(ch)) != 5:
            problems.append(f"{cid}: needs 5 distinct choices (has {len(ch)})")
        if not isinstance(ai, int) or not (0 <= ai < len(ch)):
            problems.append(f"{cid}: invalid answerIndex {ai}")
            continue
        if not tr or len(tr) != len(ch):
            problems.append(f"{cid}: choiceTraps missing/misaligned")
        else:
            if tr[ai] is not None:
                problems.append(f"{cid}: answer choice must have null trap")
            for i, t in enumerate(tr):
                if i != ai and t not in TRAPS:
                    problems.append(f"{cid}: bad trap '{t}' at choice {i}")
        if not c.get("source"):
            problems.append(f"{cid}: no source")

    # Near-duplicate stimuli across LR practice (RC questions share a passage by
    # design and are a separate section, so they are excluded here).
    def is_rc(card: dict) -> bool:
        return any(t.startswith("lsat::rc::") for t in card.get("tags", []))

    stims = [(c["id"], (c.get("stimulus") or "").lower()) for c in practice if not is_rc(c)]
    dups = []
    for i in range(len(stims)):
        for j in range(i + 1, len(stims)):
            r = SequenceMatcher(None, stims[i][1], stims[j][1]).ratio()
            if r > DUP_THRESHOLD:
                dups.append(f"{stims[i][0]} ~ {stims[j][0]} ({r:.2f})")

    skills = Counter(lr_skill(c) for c in elim)
    traps = Counter(t for c in elim for t in (c.get("choiceTraps") or []) if t)
    diffs = Counter(c.get("difficulty") for c in elim)

    print(f"Elimination-tagged LR questions: {len(elim)}")
    print(f"Structural problems: {len(problems)}")
    for p in problems:
        print(f"  - {p}")
    print(f"Near-duplicate stimuli (>{DUP_THRESHOLD}): {len(dups)}")
    for p in dups:
        print(f"  - {p}")
    print("\nVariety — by LR skill:")
    for k, n in sorted(skills.items(), key=lambda x: -x[1]):
        print(f"  {k:<24} {n}")
    print("Variety — by trap type:")
    for k, n in sorted(traps.items(), key=lambda x: -x[1]):
        print(f"  {k:<24} {n}")
    print("Variety — by difficulty:")
    for k, n in sorted(diffs.items(), key=lambda x: (x[0] is None, x[0])):
        print(f"  {k}: {n}")

    ok = not problems
    print("\n" + ("PASS: bank is structurally clean." if ok else "FAIL: fix the problems above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
