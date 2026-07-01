#!/usr/bin/env python3
"""Load the LSAT deck into the LIVE Sharpe collection.

Concept cards stay simple Basic flashcards (memory assessment); practice cards
become the interactive Sharpe LR elimination card (rule out choices, name the
trap that tempts you).

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
        lr = sharpe_lr.ensure_model(col)

        # Clean reload: drop any previously loaded LSAT notes.
        old = col.find_notes("tag:lsat::type::concept OR tag:lsat::type::practice")
        if old:
            col.remove_notes(list(old))

        counts = {"concept": 0, "practice": 0}
        for card in data["cards"]:
            if card["type"] == "concept":
                did = col.decks.id("LSAT::Concepts")
                note = col.new_note(basic)
                note.guid = "speedrun-" + card["id"]
                note["Front"] = card["front"]
                note["Back"] = card["back"]
            else:
                did = col.decks.id("LSAT::Practice")
                note = col.new_note(lr)
                note.guid = "sharpe-elim-" + card["id"]
                sharpe_lr.populate(note, card)
            tags = list(card["tags"]) + [
                f'lsat::type::{card["type"]}',
                f'src::{card["source"]}',
                f'id::{card["id"]}',
            ]
            if card["type"] == "practice":
                tags += sharpe_lr.trap_tags(card)
            note.tags = tags
            col.add_note(note, did)
            counts[card["type"]] += 1

        col.save()
        print(f"loaded concept={counts['concept']} practice={counts['practice']} into {LIVE}")
    finally:
        col.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
