#!/usr/bin/env python3
"""Update the Sharpe note-type CSS/templates in the LIVE collection and push them
with a NORMAL (incremental) sync, so card-style tweaks reach the phone without a
full-sync reset. Run with the desktop app CLOSED and the sync server running.

    out/pyenv/bin/python speedrun/scripts/refresh_templates.py
"""

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
ENDPOINT = "http://127.0.0.1:27701/"
USER, PASS = "jessie", "lsat"


def main() -> int:
    col = Collection(LIVE)
    try:
        sharpe_lr.ensure_judge_model(col)
        try:
            sharpe_lr.ensure_model(col)
        except Exception:
            pass
        auth = col.sync_login(USER, PASS, ENDPOINT)
        out = col.sync_collection(auth, False)
        print("sync required:", out.required)
        print("normal sync done — open AnkiDroid and tap Sync to pull the style update")
    finally:
        col.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
