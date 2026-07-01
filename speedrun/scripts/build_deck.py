#!/usr/bin/env python3
"""Build an Anki .apkg from speedrun/decks/lsat_seed.json using Anki's own engine.

This is a *build-time* tool (not part of the running app and not AI): it reads the
human-authored, cited JSON and produces a portable deck that loads into both the
desktop app and AnkiDroid.

Run with the dev Python that has the built backend:
    out/pyenv/bin/python speedrun/scripts/build_deck.py
Output: out/lsat_seed.apkg
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
# Same import setup the dev runner uses (source tree + built generated files).
sys.path.extend(["pylib", "qt", "out/pylib", "out/qt"])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anki.collection import Collection  # noqa: E402
from anki.exporting import AnkiPackageExporter  # noqa: E402

import sharpe_lr  # noqa: E402

DECK_JSON = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
OUT_APKG = os.path.join(ROOT, "out", "lsat_seed.apkg")
LETTERS = ["A", "B", "C", "D", "E", "F", "G"]


def nl(parts: list[str]) -> str:
    """Join lines as HTML for an Anki field."""
    return "<br>".join(parts)


def concept_fields(card: dict) -> tuple[str, str]:
    # Source is intentionally NOT shown on the card; it lives in docs/speedrun/flashcards.md.
    return card["front"], card["back"]


def practice_fields(card: dict) -> tuple[str, str]:
    parts = []
    if card.get("stimulus"):
        parts += [card["stimulus"], ""]
    parts.append(f'<b>{card["question"]}</b>')
    parts.append("")
    for i, choice in enumerate(card["choices"]):
        parts.append(f"{LETTERS[i]}. {choice}")
    front = nl(parts)
    ans_i = card["answerIndex"]
    back = nl(
        [
            f'<b>Answer: {LETTERS[ans_i]}.</b> {card["choices"][ans_i]}',
            "",
            card["explanation"],
        ]
    )
    return front, back


def main() -> int:
    with open(DECK_JSON, encoding="utf-8") as fh:
        data = json.load(fh)

    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    tmp_dir = tempfile.mkdtemp(dir=os.path.join(ROOT, "out"))
    col = Collection(os.path.join(tmp_dir, "col.anki2"))

    basic = col.models.by_name("Basic")
    lr_model = sharpe_lr.ensure_model(col)
    counts = {"concept": 0, "practice": 0}

    for card in data["cards"]:
        if card["type"] == "concept":
            did = col.decks.id("LSAT::Concepts")
            note = col.new_note(basic)
            # Stable guid keyed on our card id, so re-imports update instead of duplicate.
            note.guid = "speedrun-" + card["id"]
            front, back = concept_fields(card)
            note["Front"] = front
            note["Back"] = back
        else:
            did = col.decks.id("LSAT::Practice")
            note = col.new_note(lr_model)
            # Practice is now the interactive Sharpe LR elimination card.
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

    if os.path.exists(OUT_APKG):
        os.remove(OUT_APKG)
    exp = AnkiPackageExporter(col)
    exp.did = None          # whole (temp) collection
    exp.includeSched = False  # ship cards as new
    exp.includeMedia = False
    exp.exportInto(OUT_APKG)
    col.close()

    size_kb = os.path.getsize(OUT_APKG) // 1024
    print(f"concept={counts['concept']} practice={counts['practice']} total={sum(counts.values())}")
    print(f"wrote {OUT_APKG} ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
