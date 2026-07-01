"""Make Anki's review order concept-based for the LSAT deck (Speedrun LSAT).

Calls the Rust engine op `ReorderDeckBySkillWeakness`, which repositions the
deck's NEW cards so the weakest, most heavily-tested concept is studied first
(priority = student weakness x exam weight). It rides Anki's standard reposition
op, so it is undoable and never touches FSRS intervals.

Usage:
    # Safe demo on a throwaway collection seeded from our .apkg:
    out/pyenv/bin/python speedrun/scripts/reorder_by_concept.py --seed

    # Apply to your real desktop collection (close the Anki app first):
    out/pyenv/bin/python speedrun/scripts/reorder_by_concept.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path[:0] = ["pylib", "qt", "out/pylib", "out/qt"]

from anki.collection import Collection, ImportAnkiPackageRequest  # noqa: E402

LIVE = os.path.expanduser("~/Library/Application Support/Anki2/User 1/collection.anki2")
SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
APKG = os.path.join(ROOT, "out", "lsat_seed.apkg")
DECK = "LSAT"


def skill_tag(skill_id: str) -> str:
    return "lsat::" + skill_id.replace("_", "::", 1)


def load_seed() -> tuple[dict[str, float], dict[str, str]]:
    seed = json.load(open(SEED, encoding="utf-8"))
    scored = [s for s in seed["skills"] if s["section"] in ("LR", "RC")]
    weights = {skill_tag(s["id"]): float(s["examWeight"]) for s in scored}
    names = {skill_tag(s["id"]): s["name"] for s in seed["skills"]}
    return weights, names


def study_order(col: Collection, weights: dict[str, float], names: dict[str, str], n: int = 12):
    """New cards in the order Anki will actually show them (by position), each
    annotated with the concept it trains and its priority."""
    entries = list(col._backend.get_skill_weakness_queue(deck_id=col.decks.id(DECK), skill_weights=weights))
    by_card = {e.card_id: e for e in entries}
    new_cards = [col.get_card(c) for c in col.find_cards(f"deck:{DECK} is:new")]
    new_cards.sort(key=lambda c: c.due)  # position == the study order for new cards
    rows = []
    for card in new_cards[:n]:
        e = by_card.get(card.id)
        if e is None:
            rows.append((card.due, "(no scored concept)", 0.0))
        else:
            label = names.get(e.skill, e.skill)
            rows.append((card.due, label, e.priority))
    return rows


def show(title: str, rows) -> None:
    print(f"\n{title}")
    print(f"  {'pos':>4}  {'priority':>8}  concept")
    for pos, label, pri in rows:
        print(f"  {pos:>4}  {pri:>8.3f}  {label}")


def open_collection(seed_mode: bool) -> tuple[Collection, bool]:
    if seed_mode:
        path = os.path.join(tempfile.mkdtemp(), "col.anki2")
        col = Collection(path)
        if not os.path.exists(APKG):
            raise SystemExit(f"missing {APKG} — run build_deck.py first")
        col.import_anki_package(ImportAnkiPackageRequest(package_path=APKG))
        return col, True
    return Collection(LIVE), False


def main() -> int:
    seed_mode = "--seed" in sys.argv
    weights, names = load_seed()
    col, temp = open_collection(seed_mode)
    try:
        target = "throwaway collection (from .apkg)" if temp else LIVE
        print(f"Collection: {target}")

        before = study_order(col, weights, names)
        show("BEFORE — new-card order (insertion order):", before)

        out = col._backend.reorder_deck_by_skill_weakness(
            deck_id=col.decks.id(DECK), skill_weights=weights
        )
        print(f"\nReordered {out.count} new cards by concept priority (undo-safe).")

        after = study_order(col, weights, names)
        show("AFTER — new-card order (weakest x heaviest concept first):", after)

        pris = [p for _, _, p in after]
        print("\nSorted by descending priority:", all(pris[i] >= pris[i + 1] for i in range(len(pris) - 1)))
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
