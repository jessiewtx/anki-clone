"""Speedrun LSAT: show the two 'not-Anki' behaviors on real cards.

  1. A problem answered correctly is RETIRED -> never served again (no memorizing).
  2. A too-fast 'correct' on a problem retires that instance but gives NO mastery
     credit, so the concept stays weak and fresh problems keep coming.

Runs on a throwaway collection. We write revlog rows directly so we can control
the response time (the thing the guard keys on).

Run:
    out/pyenv/bin/python speedrun/scripts/demo_fresh_instance.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path[:0] = ["pylib", "qt", "out/pylib", "out/qt"]

from anki.collection import Collection  # noqa: E402

SKILL = "s"
WEIGHTS = {SKILL: 0.5}
PRACTICE = "lsat::type::practice"


def add_problem(col, deck_id, front) -> int:
    basic = col.models.by_name("Basic")
    note = col.new_note(basic)
    note["Front"] = front
    note["Back"] = "answer"
    note.tags = [SKILL, PRACTICE]
    col.add_note(note, deck_id)
    return col.find_cards(front)[0]


def answer(col, cid, ease, millis, rid) -> None:
    """Write a revlog row with a controlled response time (ms)."""
    col.db.execute(
        "insert into revlog (id,cid,usn,ease,ivl,lastIvl,factor,time,type) "
        "values (?,?,?,?,?,?,?,?,?)",
        rid, cid, -1, ease, 0, 0, 0, millis, 0,
    )


def show(col, label, id_by_cid) -> None:
    resp = col._backend.get_skill_weakness_queue(deck_id=col.decks.id("T"), skill_weights=WEIGHTS)
    entries = list(resp)
    served = ", ".join(f"{id_by_cid[e.card_id]}(weak {e.weakness:.2f})" for e in entries)
    print(f"  {label}\n     will serve: [{served or 'nothing'}]")


def main() -> int:
    col = Collection(os.path.join(tempfile.mkdtemp(), "col.anki2"))
    try:
        did = col.decks.id("T")
        c1 = add_problem(col, did, "PROB1")
        c2 = add_problem(col, did, "PROB2")
        c3 = add_problem(col, did, "PROB3")
        names = {c1: "PROB1", c2: "PROB2", c3: "PROB3"}
        base = int(time.time() * 1000)

        print("Three problems for one concept (all fresh):")
        show(col, "start", names)

        print("\nYou answer PROB1 correctly, but in 2 seconds (memorized / guessed):")
        answer(col, c1, ease=3, millis=2_000, rid=base + 1)
        show(col, "after fast-correct on PROB1", names)
        print("     -> PROB1 is retired (won't reappear), but the concept is still weak 1.00,")
        print("        so fresh problems keep coming. Memorizing one answer didn't help.")

        print("\nYou answer PROB2 correctly, taking 15 seconds (real reasoning):")
        answer(col, c2, ease=3, millis=15_000, rid=base + 2)
        show(col, "after slow-correct on PROB2", names)
        print("     -> PROB2 retired AND the concept weakness drops (real mastery credit).")

        print("\nContrast with stock Anki: it would show PROB1 again on a timer — you'd")
        print("just recall 'the answer is C'. Here a solved problem never returns.")
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
