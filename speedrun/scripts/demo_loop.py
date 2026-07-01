"""Speedrun LSAT: watch the concept queue + honest scores move as you study.

Runs entirely on a THROWAWAY collection seeded from out/lsat_seed.apkg, so your
live desktop/phone data is never touched. It:

  1. Shows the concept queue (what you'd study first) and the three scores BEFORE
     any studying -> memory/performance have no data, readiness refuses (give-up).
  2. Simulates a study session where you ACE a few top concepts (Flaw, Inference,
     Necessary Assumption) and miss the rest.
  3. Shows the queue AFTER -> the mastered concepts drop down (the app moves on to
     your next weak spot), and memory/performance now report a value WITH A RANGE,
     while readiness still honestly says "not enough data".

Run:
    out/pyenv/bin/python speedrun/scripts/demo_loop.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path[:0] = ["pylib", "qt", "out/pylib", "out/qt"]

from anki.collection import Collection, ImportAnkiPackageRequest  # noqa: E402

SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
APKG = os.path.join(ROOT, "out", "lsat_seed.apkg")
DECK = "LSAT"

# The give-up rule (same numbers as compute_scores.py).
MIN_PERFORMANCE_ATTEMPTS = 200
MIN_COVERAGE = 0.50

# The concepts the simulated student is already good at.
MASTERED = {
    "lsat::lr::flaw",
    "lsat::lr::inference",
    "lsat::lr::necessary_assumption",
}


def skill_tag(skill_id: str) -> str:
    return "lsat::" + skill_id.replace("_", "::", 1)


def wilson(correct: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = correct / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, center - margin), min(1.0, center + margin))


def accuracy(col: Collection, card_ids: list[int]) -> tuple[int, int]:
    if not card_ids:
        return (0, 0)
    ids = ",".join(str(int(c)) for c in card_ids)
    rows = col.db.all(f"select ease from revlog where cid in ({ids}) and ease between 1 and 4")
    return (sum(1 for (e,) in rows if e >= 2), len(rows))


def concept_priorities(col, weights, names, n=6):
    """Per-skill priority = weakness x exam_weight, computed from the revlog exactly
    like the Rust engine (weakness = 1 - correct/reviews; no history => 1.0)."""
    rows = []
    for tag, wt in weights.items():
        c, ntot = accuracy(col, list(col.find_cards(f'deck:{DECK} "tag:{tag}"')))
        weak = 1.0 if ntot == 0 else 1.0 - c / ntot
        rows.append((names.get(tag, tag), weak, wt, weak * wt))
    rows.sort(key=lambda r: -r[3])
    return rows[:n]


def coverage(col, scored) -> float:
    covered = sum(1 for s in scored if col.find_cards(f'deck:{DECK} "tag:{skill_tag(s["id"])}"'))
    return covered / len(scored) if scored else 0.0


def snapshot(col, weights, names, scored, label: str) -> None:
    print(f"\n================  {label}  ================")
    print("Concept queue — what you'd study first (weakness x exam weight):")
    for i, (nm, w, wt, pri) in enumerate(concept_priorities(col, weights, names), 1):
        print(f"  {i}. {nm:<28} weakness {w:.2f} x weight {wt:.2f} = {pri:.3f}")

    all_cards = list(col.find_cards(f"deck:{DECK}"))
    prac_cards = list(col.find_cards(f'deck:{DECK} "tag:lsat::type::practice"'))
    m_c, m_n = accuracy(col, all_cards)
    p_c, p_n = accuracy(col, prac_cards)
    cov = coverage(col, scored)

    print("\nScores:")
    if m_n == 0:
        print("  Memory:      no data yet (0 reviews)")
    else:
        mp, mlo, mhi = wilson(m_c, m_n)
        print(f"  Memory:      {mp*100:.0f}%  (range {mlo*100:.0f}-{mhi*100:.0f}%)  over {m_n} reviews")
    if p_n == 0:
        print("  Performance: no data yet (0 attempts)")
    else:
        pp, plo, phi = wilson(p_c, p_n)
        print(f"  Performance: {pp*100:.0f}%  (range {plo*100:.0f}-{phi*100:.0f}%)  over {p_n} attempts")

    missing = []
    if p_n < MIN_PERFORMANCE_ATTEMPTS:
        missing.append(f"need >={MIN_PERFORMANCE_ATTEMPTS} graded practice attempts (have {p_n})")
    if cov < MIN_COVERAGE:
        missing.append(f"need >={int(MIN_COVERAGE*100)}% coverage (have {cov*100:.0f}%)")
    if missing:
        print(f"  Readiness:   NOT ENOUGH DATA — " + "; ".join(missing))
    else:
        pp, plo, phi = wilson(p_c, p_n)
        print(f"  Readiness:   {120+pp*60:.0f}  (range {120+plo*60:.0f}-{120+phi*60:.0f}) on the 120-180 scale")
    print(f"  (coverage: {cov*100:.0f}% of scored LSAT skills)")


def study(col, weights) -> tuple[int, int]:
    """One realistic pass: answer each card once. Good on a mastered skill, Again
    otherwise (a student who genuinely knows only a few concepts)."""
    correct = total = 0
    for cid in col.find_cards(f"deck:{DECK}"):
        card = col.get_card(cid)
        note = col.get_note(card.nid)
        skills = [t for t in note.tags if t in weights]
        good = (not skills) or any(s in MASTERED for s in skills)
        ease = 3 if good else 1
        card.start_timer()
        col.sched.answerCard(card, ease)
        total += 1
        correct += 1 if ease >= 2 else 0
    return correct, total


def main() -> int:
    seed = json.load(open(SEED, encoding="utf-8"))
    scored = [s for s in seed["skills"] if s["section"] in ("LR", "RC")]
    weights = {skill_tag(s["id"]): float(s["examWeight"]) for s in scored}
    names = {skill_tag(s["id"]): s["name"] for s in seed["skills"]}

    col = Collection(os.path.join(tempfile.mkdtemp(), "col.anki2"))
    try:
        col.import_anki_package(ImportAnkiPackageRequest(package_path=APKG))

        snapshot(col, weights, names, scored, "BEFORE you study")

        print("\n>>> Simulating a session: you ACE Flaw / Inference / Necessary Assumption, miss the rest...")
        c, t = study(col, weights)
        print(f">>> answered {t} cards ({c} correct, {t - c} wrong)")

        snapshot(col, weights, names, scored, "AFTER you study")
        print("\nTakeaways:")
        print("  - Concepts you proved you know dropped DOWN the queue (app moves to your next gap).")
        print("  - Memory & Performance now show a NUMBER WITH A RANGE, not a fake precise score.")
        print("  - Readiness still refuses — the give-up rule protects you from a bogus 120-180.")
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
