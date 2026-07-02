# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Sharpe: ship the LSAT deck inside the app and auto-load it on first launch.

A fresh install has an empty collection. Rather than make the student download a
separate .apkg and import it by hand, we bundle ``lsat_seed.apkg`` next to the
``aqt`` package (the installer copies it there) and import it once, the first time
a collection opens without the LSAT deck. Guarded by a collection config flag so
it never re-imports or fights the user's own edits.
"""

from __future__ import annotations

import os
from pathlib import Path

from aqt import gui_hooks

_FLAG = "sharpe_seeded"


def _find_apkg() -> str | None:
    import aqt

    aqt_dir = Path(aqt.__file__).resolve().parent
    candidates = [
        aqt_dir / "lsat_seed.apkg",                       # bundled in the app
        Path.cwd() / "out" / "lsat_seed.apkg",            # dev: ./run from repo root
        aqt_dir.parent.parent / "out" / "lsat_seed.apkg",  # dev: repo/qt/aqt -> repo/out
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _already_has_deck(col) -> bool:
    try:
        return bool(col.decks.by_name("LSAT::Practice") or col.decks.by_name("LSAT"))
    except Exception:
        return False


def seed_collection(col, apkg: str) -> None:
    """Import the bundled deck into ``col`` via the Rust backend (used by the hook
    and tests). Imported as new cards (no scheduling), so it's a clean starting deck."""
    from anki.collection import ImportAnkiPackageOptions, ImportAnkiPackageRequest

    req = ImportAnkiPackageRequest(
        package_path=os.path.abspath(apkg),
        options=ImportAnkiPackageOptions(
            merge_notetypes=False, with_scheduling=False, with_deck_configs=False
        ),
    )
    col.import_anki_package(req)


def _maybe_seed(mw, col) -> None:
    try:
        if col.get_config(_FLAG, False):
            return
        if _already_has_deck(col):
            col.set_config(_FLAG, True)
            return
        apkg = _find_apkg()
        if not apkg or not os.path.exists(apkg):
            return
        seed_collection(col, apkg)
        col.set_config(_FLAG, True)
        try:
            mw.reset()
        except Exception:
            pass
    except Exception as e:  # never block startup over seeding
        print("sharpe seed failed:", e)


def init(mw) -> None:
    gui_hooks.collection_did_load.append(lambda col: _maybe_seed(mw, col))
    # If a collection is already open when we register (later restarts), seed now.
    if getattr(mw, "col", None) is not None:
        _maybe_seed(mw, mw.col)
