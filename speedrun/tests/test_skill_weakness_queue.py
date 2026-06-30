"""Python test for the Rust skill-weakness queue RPC (Speedrun LSAT).

Exercises the new `GetSkillWeaknessQueue` backend call end-to-end across the
Rust<->Python boundary: builds a collection, adds skill-tagged cards, and checks
the returned ordering is `weakness * exam_weight`, descending.

Run with the dev backend:
    out/pyenv/bin/python speedrun/tests/test_skill_weakness_queue.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path[:0] = ["pylib", "qt", "out/pylib", "out/qt"]

from anki.collection import Collection  # noqa: E402


def _add_note(col: "Collection", deck_id: int, front: str, tags: list[str]) -> None:
    basic = col.models.by_name("Basic")
    note = col.new_note(basic)
    note["Front"] = front
    note["Back"] = "answer"
    note.tags = tags
    col.add_note(note, deck_id)


def test_skill_weakness_queue() -> None:
    col = Collection(os.path.join(tempfile.mkdtemp(), "col.anki2"))
    try:
        did = col.decks.id("T")
        _add_note(col, did, "card a", ["skill_a"])
        _add_note(col, did, "card b", ["skill_b"])
        # Card with no weighted skill must be excluded from the queue.
        _add_note(col, did, "card c", ["unweighted"])

        weights = {"skill_a": 0.9, "skill_b": 0.1}
        # Anki unwraps single-field responses, so this returns the entries list.
        resp = col._backend.get_skill_weakness_queue(deck_id=did, skill_weights=weights)
        entries = list(resp)

        # Only the two weighted cards are returned.
        assert len(entries) == 2, f"expected 2 entries, got {len(entries)}"
        # Both cards are new (no review history) => weakness 1.0, so priority == weight.
        assert entries[0].skill == "skill_a", f"first skill was {entries[0].skill}"
        assert abs(entries[0].priority - 0.9) < 1e-6, entries[0].priority
        assert entries[0].weakness == 1.0, entries[0].weakness
        assert entries[1].skill == "skill_b", f"second skill was {entries[1].skill}"
        assert abs(entries[1].priority - 0.1) < 1e-6, entries[1].priority
        # Ordering is strictly descending by priority.
        assert entries[0].priority > entries[1].priority
        print("PYTHON TEST PASSED: skill-weakness queue ordering is correct")
    finally:
        col.close()


if __name__ == "__main__":
    test_skill_weakness_queue()
