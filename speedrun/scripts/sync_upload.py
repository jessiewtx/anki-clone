"""Push the desktop collection to the local Anki sync server (Speedrun LSAT).

Forces the server to match the desktop (upload=True), so after a desktop-side
change (e.g. the concept-based reorder) the phone gets it on its next sync.

Prereqs:
- Anki desktop app CLOSED (so the collection isn't locked).
- Local sync server running on 127.0.0.1:27701 with user jessie:lsat.

Run:
    out/pyenv/bin/python speedrun/scripts/sync_upload.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path[:0] = ["pylib", "qt", "out/pylib", "out/qt"]

from anki.collection import Collection  # noqa: E402

COLLECTION = os.path.expanduser("~/Library/Application Support/Anki2/User 1/collection.anki2")
ENDPOINT = "http://127.0.0.1:27701/"
USER, PASS = "jessie", "lsat"


def main() -> int:
    col = Collection(COLLECTION)
    try:
        n_new = len(col.find_cards("deck:LSAT is:new"))
        print(f"desktop LSAT new cards: {n_new}")
        auth = col.sync_login(USER, PASS, ENDPOINT)
        col.full_upload_or_download(auth=auth, server_usn=None, upload=True)
        print("UPLOADED concept-ordered collection to sync server")
        print("Next: open AnkiDroid on the phone and tap Sync (it will download).")
        return 0
    except Exception as exc:  # noqa: BLE001
        print("sync upload failed:", exc)
        return 1
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
