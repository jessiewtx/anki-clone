#!/usr/bin/env python3
"""DEMO ONLY: show what the honest readiness score looks like once enough data
exists. Builds a THROWAWAY collection, injects clearly-labeled SIMULATED graded
attempts, and reuses the real compute_scores logic to print Memory / Performance /
Readiness (projected LSAT 120-180 + range). It does NOT touch your real collection
and makes NO claim about your real readiness — it demonstrates the mechanism.

    out/pyenv/bin/python speedrun/scripts/demo_score.py
"""

import json
import os
import random
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
sys.path.extend(["pylib", "qt", "out/pylib", "out/qt"])
sys.path.insert(0, HERE)

from anki.collection import Collection  # noqa: E402

import compute_scores as cs  # noqa: E402
import sharpe_lr  # noqa: E402

SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
N_ATTEMPTS = 230
P_CORRECT = 0.58


def build_temp() -> str:
    data = json.load(open(SEED, encoding="utf-8"))
    tmp = tempfile.mkdtemp(dir=os.path.join(ROOT, "out"))
    path = os.path.join(tmp, "col.anki2")
    col = Collection(path)
    basic = col.models.by_name("Basic")
    judge = sharpe_lr.ensure_judge_model(col)
    for card in data["cards"]:
        if card["type"] == "concept":
            n = col.new_note(basic)
            n["Front"], n["Back"] = card["front"], card["back"]
            n.tags = list(card["tags"]) + ["lsat::type::concept"]
            col.add_note(n, col.decks.id("LSAT::Concepts"))
        elif card.get("choiceTraps"):
            for spec in sharpe_lr.judge_specs(card):
                n = col.new_note(judge)
                sharpe_lr.populate_judge(n, spec)
                n.tags = sharpe_lr.judge_note_tags(spec)
                col.add_note(n, col.decks.id("LSAT::Practice"))
    # Inject SIMULATED graded attempts on the practice cards.
    practice = list(col.find_cards('deck:LSAT "tag:lsat::type::practice"'))
    now = int(time.time() * 1000)
    rows = []
    for i in range(N_ATTEMPTS):
        cid = int(practice[i % len(practice)])
        ease = 3 if random.random() < P_CORRECT else 1  # Good vs Again
        rows.append((now + i, cid, -1, ease, 0, 0, 0, 12000, 1))
    col.db.executemany(
        "insert into revlog (id,cid,usn,ease,ivl,lastIvl,factor,time,type)"
        " values (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    col.save()
    col.close()
    return path


def main() -> int:
    random.seed(11)
    path = build_temp()
    # Point the real compute at the throwaway collection + a scratch output.
    cs.COLLECTION = path
    cs.OUT = path + ".scores.json"
    print("=== DEMO (SIMULATED DATA — not your real readiness) ===")
    print(f"Injected {N_ATTEMPTS} simulated attempts (~{int(P_CORRECT*100)}% correct)\n")
    return cs.main()


if __name__ == "__main__":
    raise SystemExit(main())
