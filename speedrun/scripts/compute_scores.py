"""Compute the three HONEST scores (memory / performance / readiness) for the
Speedrun LSAT dashboard, straight from the Anki collection — no made-up numbers.

- memory:      recall success rate on real reviews, with a Wilson 95% interval.
- performance: accuracy on practice (exam-style) cards, with a Wilson interval.
- readiness:   projected LSAT 120-180 ONLY if the give-up rule is satisfied;
               otherwise it abstains and reports exactly what data is missing.
- coverage:    % of the exam's scored skills that the deck actually covers.
- next_to_study: top skills by the Rust skill-weakness queue (weakness x weight).

Run with the dev backend:
    out/pyenv/bin/python speedrun/scripts/compute_scores.py
Writes: speedrun/web/public/scores.json
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path[:0] = ["pylib", "qt", "out/pylib", "out/qt"]

from anki.collection import Collection  # noqa: E402

COLLECTION = os.path.expanduser(
    "~/Library/Application Support/Sharpe/User 1/collection.anki2"
)
SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
OUT = os.path.join(ROOT, "speedrun", "web", "public", "scores.json")

# Give-up rule (stated, enforced): no readiness number until BOTH hold.
MIN_PERFORMANCE_ATTEMPTS = 50
MIN_COVERAGE = 0.50  # fraction of exam *weight* (not skill count) that must be covered


def wilson(correct: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Return (point, lo, hi). With no data, point is undefined -> full 0..1 band."""
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = correct / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, center - margin), min(1.0, center + margin))


def confidence(n: int) -> str:
    if n >= 200:
        return "high"
    if n >= 50:
        return "medium"
    if n >= 1:
        return "low"
    return "none"


def skill_tag(skill_id: str) -> str:
    # "lr_necessary_assumption" -> "lsat::lr::necessary_assumption"
    return "lsat::" + skill_id.replace("_", "::", 1)


def accuracy_over_cards(col: Collection, card_ids: list[int]) -> tuple[int, int]:
    """(correct, total) over the revlog of the given cards. A press of Again
    (ease 1) is incorrect; Hard/Good/Easy (2..4) correct; manual (0) ignored."""
    if not card_ids:
        return (0, 0)
    ids = ",".join(str(int(c)) for c in card_ids)
    rows = col.db.all(
        f"select ease from revlog where cid in ({ids}) and ease between 1 and 4"
    )
    correct = sum(1 for (ease,) in rows if ease >= 2)
    return (correct, len(rows))


def main() -> int:
    col = Collection(COLLECTION)
    try:
        seed = json.load(open(SEED, encoding="utf-8"))
        scored = [s for s in seed["skills"] if s["section"] in ("LR", "RC")]
        weights = {skill_tag(s["id"]): float(s["examWeight"]) for s in scored}

        deck_id = col.decks.id("LSAT")

        # ---- coverage ----
        # Weighted coverage: high-weight (and internally similar) LR skills count
        # for more, so you need not cover every skill/section to project a score.
        covered = []
        covered_w = 0.0
        total_w = sum(float(s["examWeight"]) for s in scored)
        for s in scored:
            tag = skill_tag(s["id"])
            if col.find_cards(f'deck:LSAT "tag:{tag}"'):
                covered.append(s["id"])
                covered_w += float(s["examWeight"])
        coverage_pct = covered_w / total_w if total_w else 0.0

        # ---- memory (all reviews in the deck) ----
        all_cards = list(col.find_cards("deck:LSAT"))
        m_correct, m_total = accuracy_over_cards(col, all_cards)
        m_p, m_lo, m_hi = wilson(m_correct, m_total)

        # ---- performance (practice / exam-style cards only) ----
        practice_cards = list(col.find_cards('deck:LSAT "tag:lsat::type::practice"'))
        p_correct, p_total = accuracy_over_cards(col, practice_cards)
        perf_p, perf_lo, perf_hi = wilson(p_correct, p_total)

        # ---- readiness (give-up rule) ----
        reasons = []
        missing = []
        if p_total < MIN_PERFORMANCE_ATTEMPTS:
            missing.append(
                f"need >= {MIN_PERFORMANCE_ATTEMPTS} graded practice attempts "
                f"(have {p_total})"
            )
        if coverage_pct < MIN_COVERAGE:
            missing.append(
                f"need >= {int(MIN_COVERAGE*100)}% weighted coverage "
                f"(have {coverage_pct*100:.0f}%)"
            )
        gave_up = bool(missing)
        readiness = {
            "scale": "120-180",
            "give_up_rule": (
                f">= {MIN_PERFORMANCE_ATTEMPTS} graded practice attempts AND "
                f">= {int(MIN_COVERAGE*100)}% coverage"
            ),
            "gave_up": gave_up,
            "missing": missing,
        }
        if not gave_up:
            # Map performance accuracy onto the 120-180 scale (documented method).
            point = 120 + perf_p * 60
            lo = 120 + perf_lo * 60
            hi = 120 + perf_hi * 60
            readiness.update(
                {
                    "point": round(point),
                    "lo": round(lo),
                    "hi": round(hi),
                    "confidence": confidence(p_total),
                    "reasons": [
                        f"performance {perf_p*100:.0f}% over {p_total} attempts",
                        f"coverage {coverage_pct*100:.0f}%",
                    ],
                }
            )

        # ---- next to study (Rust skill-weakness queue) ----
        entries = list(col._backend.get_skill_weakness_queue(deck_id=deck_id, skill_weights=weights))
        by_skill: dict[str, dict] = {}
        for e in entries:
            cur = by_skill.get(e.skill)
            if cur is None or e.priority > cur["priority"]:
                by_skill[e.skill] = {
                    "skill": e.skill,
                    "weakness": round(e.weakness, 3),
                    "exam_weight": round(e.exam_weight, 3),
                    "priority": round(e.priority, 3),
                }
        next_to_study = sorted(by_skill.values(), key=lambda x: -x["priority"])[:3]

        out = {
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "exam": "LSAT",
            "user": "demo",
            "coverage": {
                "covered_skills": len(covered),
                "total_skills": len(scored),
                "pct": round(coverage_pct, 3),
            },
            "memory": {
                "point": round(m_p, 3),
                "lo": round(m_lo, 3),
                "hi": round(m_hi, 3),
                "n_reviews": m_total,
                "confidence": confidence(m_total),
                "method": "recall success rate on reviews (Wilson 95% CI)",
            },
            "performance": {
                "point": round(perf_p, 3),
                "lo": round(perf_lo, 3),
                "hi": round(perf_hi, 3),
                "n_attempts": p_total,
                "confidence": confidence(p_total),
                "method": "accuracy on practice/exam-style cards (Wilson 95% CI)",
            },
            "readiness": readiness,
            "next_to_study": next_to_study,
        }

        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print(json.dumps(out, indent=2))
        print(f"\nwrote {OUT}")
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
