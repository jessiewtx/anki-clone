#!/usr/bin/env python3
"""Load the LSAT deck into the LIVE Sharpe collection.

Two decks:
  * LSAT::Concepts  — plain Basic memory flashcards (the "assess" layer).
  * LSAT::Practice  — Mode 1 "Trap Spotter" judge cards: one choice at a time,
    Right/Wrong, and if Wrong, name the flaw. Built from the trap-tagged
    questions (one judge card per choice).

Run with the Sharpe app CLOSED (the collection is single-writer):
    out/pyenv/bin/python speedrun/scripts/load_gym.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
sys.path.extend(["pylib", "qt", "out/pylib", "out/qt"])
sys.path.insert(0, HERE)

from anki.collection import Collection  # noqa: E402

import sharpe_lr  # noqa: E402

LIVE = os.path.expanduser("~/Library/Application Support/Sharpe/User 1/collection.anki2")
SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")


def main() -> int:
    if not os.path.exists(LIVE):
        print(f"live collection not found: {LIVE}")
        return 1

    data = json.load(open(SEED, encoding="utf-8"))
    col = Collection(LIVE)
    try:
        basic = col.models.by_name("Basic")
        judge = sharpe_lr.ensure_judge_model(col)

        # Clean reload: drop any previously loaded LSAT notes (concept/practice).
        old = col.find_notes("tag:lsat::type::concept OR tag:lsat::type::practice")
        if old:
            col.remove_notes(list(old))

        counts = {"concept": 0, "judge": 0}
        for card in data["cards"]:
            if card["type"] == "concept":
                did = col.decks.id("LSAT::Concepts")
                note = col.new_note(basic)
                note.guid = "speedrun-" + card["id"]
                note["Front"] = card["front"]
                note["Back"] = card["back"]
                note.tags = list(card["tags"]) + [
                    "lsat::type::concept",
                    f'src::{card["source"]}',
                    f'id::{card["id"]}',
                ]
                col.add_note(note, did)
                counts["concept"] += 1
            else:  # practice -> Mode 1 judge cards (needs trap data)
                if not card.get("choiceTraps"):
                    continue
                did = col.decks.id("LSAT::Practice")
                for spec in sharpe_lr.judge_specs(card):
                    note = col.new_note(judge)
                    note.guid = "sharpe-judge-" + spec["qid"]
                    sharpe_lr.populate_judge(note, spec)
                    note.tags = sharpe_lr.judge_note_tags(spec) + [f'src::{card["source"]}']
                    col.add_note(note, did)
                    counts["judge"] += 1

        col.save()
        print(f"loaded concept={counts['concept']} judge={counts['judge']} into {LIVE}")
    finally:
        col.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
