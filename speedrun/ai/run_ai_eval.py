"""Speedrun LSAT: one-command AI eval (held-out, re-runnable).

Generates a batch of Flaw questions two ways -- the rules generator (AI-off) and
the naive keyword baseline -- runs every card through card-check, and reports how
each does. The generator should match the baseline on validity/traceability while
crushing it on NOVELTY (the baseline only recycles the existing deck).

Run:
    out/pyenv/bin/python speedrun/ai/run_ai_eval.py
Writes: speedrun/evals/ai_eval.json
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from baseline import KeywordBaseline  # noqa: E402
from cardcheck import CRITERIA, check_question, deck_stimuli  # noqa: E402
from generator import RulesGenerator  # noqa: E402

N = 12
OUT = os.path.join(ROOT, "speedrun", "evals", "ai_eval.json")


def summarize(qs: list[dict], corpus: list[str]):
    rows = [check_question(q, corpus) for q in qs]
    n = len(rows) or 1
    rates = {c: sum(r[c] for r in rows) / n for c in CRITERIA}
    overall = sum(r["pass"] for r in rows) / n
    return rows, rates, overall


def show_sample(q: dict) -> None:
    print("\nSample generated question (rules generator):")
    print(f"  Stimulus: {q['stimulus']}")
    print(f"  Q: {q['question']} ...")
    for i, c in enumerate(q["choices"]):
        mark = "  <-- correct" if i == q["answerIndex"] else ""
        print(f"     ({chr(65+i)}) {c}{mark}")
    print(f"  Source: {q['source']['name']} — {q['source']['url']}")


def main() -> int:
    corpus = deck_stimuli()
    gen_qs = RulesGenerator().generate(N)
    base_qs = KeywordBaseline().generate(N)

    _, g_rates, g_overall = summarize(gen_qs, corpus)
    _, b_rates, b_overall = summarize(base_qs, corpus)

    print(f"AI question-generation eval  (n={N} per method, novelty sim < 0.6)")
    print(f"\n  {'criterion':<14}{'generator':>12}{'baseline':>12}")
    for c in CRITERIA:
        print(f"  {c:<14}{g_rates[c]*100:>11.0f}%{b_rates[c]*100:>11.0f}%")
    print(f"  {'OVERALL pass':<14}{g_overall*100:>11.0f}%{b_overall*100:>11.0f}%")

    verdict = "BEATS" if g_overall > b_overall else "does NOT beat"
    print(f"\n=> Rules generator {verdict} the baseline "
          f"({g_overall*100:.0f}% vs {b_overall*100:.0f}% valid+novel+cited).")

    show_sample(gen_qs[0])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "type": "ai_cardcheck",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "n_per_arm": N,
                "novelty_threshold": 0.6,
                "generator": {"overall_pass": round(g_overall, 3), "criteria": {k: round(v, 3) for k, v in g_rates.items()}},
                "baseline": {"overall_pass": round(b_overall, 3), "criteria": {k: round(v, 3) for k, v in b_rates.items()}},
                "sample_generated": gen_qs[0],
            },
            fh,
            indent=2,
        )
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
