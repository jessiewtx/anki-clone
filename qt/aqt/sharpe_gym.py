# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Sharpe elimination gym: capture which traps tempt the student, and re-rank
the practice deck so the Rust weakness queue serves those traps back.

Two pieces:
  * a JS->Python bridge (``webview_did_receive_js_message``) that records each
    elimination attempt (which trap ids were left in) into a small per-profile
    SQLite file, and
  * a "Re-rank by my traps" action that turns that history into per-trap weights
    and feeds them, alongside the LSAT skill weights, into the *existing* Rust
    ``reorder_deck_by_skill_weakness`` RPC. Because the engine treats any weighted
    tag as a skill, ``trap::<id>`` tags become first-class priorities — no fake
    Python reorder, and it ships to the phone with the shared engine.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any

from aqt import gui_hooks
from aqt.qt import QAction, qconnect
from aqt.speedrun_scores import SKILL_WEIGHTS
from aqt.utils import tooltip

DECK = "LSAT::Practice"
_PREFIX = "sharpe:attempt:"


def _db_path(mw) -> str:
    return os.path.join(mw.pm.profileFolder(), "sharpe.db")


def _conn(mw) -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(mw))
    con.execute(
        "CREATE TABLE IF NOT EXISTS attempts("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " ts INTEGER, qid TEXT, skill TEXT, difficulty TEXT,"
        " clean INTEGER, elim_correct INTEGER, tempted TEXT)"
    )
    return con


def record_attempt(mw, payload: dict) -> None:
    """Persist one elimination attempt. Skill/difficulty come from the card now
    being reviewed (the message fires from the reviewer's answer side)."""
    skill, difficulty = "", ""
    try:
        card = mw.reviewer.card if mw.reviewer else None
        if card is not None:
            note = card.note()
            for t in note.tags:
                if t.startswith("lsat::lr::") or t.startswith("lsat::rc::"):
                    skill = t
                    break
            try:
                difficulty = note["Difficulty"]
            except Exception:
                pass
    except Exception:
        pass

    tempted = [t for t in (payload.get("tempted") or []) if t and t != "unknown"]
    con = _conn(mw)
    con.execute(
        "INSERT INTO attempts(ts, qid, skill, difficulty, clean, elim_correct, tempted)"
        " VALUES(?,?,?,?,?,?,?)",
        (
            int(time.time()),
            str(payload.get("qid", "")),
            skill,
            str(difficulty),
            1 if payload.get("clean") else 0,
            1 if payload.get("elimCorrect") else 0,
            json.dumps(tempted),
        ),
    )
    con.commit()
    con.close()


def trap_weights(mw) -> dict[str, float]:
    """``trap::<id>`` -> temptation rate in 0..1 (share of attempts in which that
    trap was left in). Higher = you fall for it more, so it should come back."""
    con = _conn(mw)
    rows = con.execute("SELECT tempted FROM attempts").fetchall()
    con.close()
    n = len(rows)
    if n == 0:
        return {}
    counts: dict[str, int] = {}
    for (blob,) in rows:
        try:
            for t in json.loads(blob):
                counts[t] = counts.get(t, 0) + 1
        except Exception:
            pass
    return {f"trap::{t}": c / n for t, c in counts.items()}


def _on_js_message(handled: tuple[bool, Any], message: str, context: Any) -> tuple[bool, Any]:
    if isinstance(message, str) and message.startswith(_PREFIX):
        from aqt import mw

        try:
            record_attempt(mw, json.loads(message[len(_PREFIX):]))
        except Exception as e:  # never break the reviewer over logging
            print("sharpe: attempt record failed:", e)
        return (True, None)
    return handled


def rerank(mw) -> None:
    if not mw.col:
        return
    deck = mw.col.decks.by_name(DECK)
    if not deck:
        tooltip(f"No {DECK} deck found.")
        return

    weights = dict(SKILL_WEIGHTS)
    traps = trap_weights(mw)
    weights.update(traps)

    try:
        out = mw.col._backend.reorder_deck_by_skill_weakness(
            deck_id=deck["id"], skill_weights=weights
        )
        count = getattr(out, "count", 0)
    except Exception as e:
        tooltip(f"Re-rank failed: {e}")
        return

    mw.reset()
    if traps:
        top = sorted(traps.items(), key=lambda kv: kv[1], reverse=True)[:3]
        names = ", ".join(t.split("::")[-1].replace("_", " ") for t, _ in top)
        tooltip(f"Re-ranked {count} practice cards toward your weak traps: {names}")
    else:
        tooltip(f"Re-ranked {count} practice cards by concept weakness (no trap history yet).")


def init(mw) -> None:
    gui_hooks.webview_did_receive_js_message.append(_on_js_message)
    act = QAction("Sharpe: Re-rank by my traps", mw)
    qconnect(act.triggered, lambda: rerank(mw))
    mw.form.menuTools.addAction(act)
