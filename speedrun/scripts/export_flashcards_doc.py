"""Export every flashcard (front/back) + its source to docs/speedrun/flashcards.md.

The source is deliberately kept OFF the card face; this doc is the single place
that records, for each card, its content and the source it is grounded in / modeled
on. Regenerate whenever the deck changes:

    out/pyenv/bin/python speedrun/scripts/export_flashcards_doc.py

Sourcing / copyright: concept cards define official LSAT skills, grounded in the
cited references; practice items are ORIGINAL questions written in the format of
official LSAT questions (LSAC's free official PrepTests on LawHub). No copyrighted
exam text is reproduced.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
OUT = os.path.join(ROOT, "docs", "speedrun", "flashcards.md")
LETTERS = ["A", "B", "C", "D", "E", "F", "G"]


def src_md(sources: dict, key: str) -> str:
    s = sources.get(key, {})
    name, url = s.get("name", key), s.get("url", "")
    return f"[{name}]({url})" if url else name


def tags_md(tags: list[str]) -> str:
    return ", ".join(f"`{t}`" for t in tags)


def main() -> int:
    d = json.load(open(SEED, encoding="utf-8"))
    sources = d["sources"]
    concept = [c for c in d["cards"] if c["type"] == "concept"]
    practice = [c for c in d["cards"] if c["type"] == "practice"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    L: list[str] = []
    L.append("# Speedrun LSAT — Flashcards")
    L.append("")
    L.append(
        f"_Auto-generated from `speedrun/decks/lsat_seed.json` by "
        f"`speedrun/scripts/export_flashcards_doc.py`. Last updated {today}._"
    )
    L.append("")
    L.append(
        "**Sourcing.** Concept cards define official LSAT skills, grounded in the "
        "cited references. Practice items are **original** questions written in the "
        "format of official LSAT questions (see LSAC's free official PrepTests on "
        "[LawHub](https://lawhub.lsac.org)); **no copyrighted exam text is "
        "reproduced**. Each card lists the source it is grounded in / modeled on."
    )
    L.append("")
    L.append(
        f"**Totals:** {len(concept)} concept cards, {len(practice)} practice "
        f"questions ({len(d['cards'])} total)."
    )

    L.append("")
    L.append("## Concept cards")
    for c in concept:
        L.append("")
        L.append(f"### {c['id']}")
        L.append(f"- **Front:** {c['front']}")
        L.append(f"- **Back:** {c['back']}")
        L.append(f"- **Tags:** {tags_md(c['tags'])}")
        L.append(f"- **Source:** {src_md(sources, c['source'])}")

    L.append("")
    L.append("## Practice questions")
    for c in practice:
        L.append("")
        L.append(f"### {c['id']}")
        if c.get("stimulus"):
            L.append(f"- **Stimulus:** {c['stimulus']}")
        L.append(f"- **Question:** {c['question']}")
        for i, ch in enumerate(c["choices"]):
            L.append(f"  - {LETTERS[i]}. {ch}")
        ai = c["answerIndex"]
        L.append(f"- **Answer:** {LETTERS[ai]}. {c['choices'][ai]}")
        L.append(f"- **Explanation:** {c['explanation']}")
        L.append(f"- **Tags:** {tags_md(c['tags'])}")
        L.append(f"- **Source:** {src_md(sources, c['source'])}")
    L.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print(f"wrote {OUT}: {len(concept)} concept + {len(practice)} practice cards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
