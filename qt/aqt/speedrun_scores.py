# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun LSAT: an in-app honest readiness view.

Adds a Tools-menu dialog that shows the three scores (Memory, Performance,
Readiness) straight from the open collection, each with a point estimate, a
likely range (Wilson 95% interval), coverage, a confidence indicator, the
reasons behind it, and the give-up rule. It never shows a readiness number
unless the give-up rule is satisfied.

The "best next thing to study" is powered by our Rust engine change
(GetSkillWeaknessQueue), so the honesty field is backed by the shared engine.
"""

from __future__ import annotations

import math
from datetime import datetime

from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    Qt,
    QVBoxLayout,
    QWidget,
)

DECK = "LSAT"
PRACTICE_TAG = "lsat::type::practice"
MIN_PERFORMANCE_ATTEMPTS = 50
MIN_COVERAGE = 0.50  # fraction of exam *weight* (not skill count) that must be covered

# Scored LSAT skills (tag -> exam weight), embedded so the view works in the
# packaged app without the repo's deck JSON.
SKILL_WEIGHTS = {
    "lsat::lr::necessary_assumption": 0.09,
    "lsat::lr::sufficient_assumption": 0.04,
    "lsat::lr::strengthen": 0.07,
    "lsat::lr::weaken": 0.08,
    "lsat::lr::flaw": 0.10,
    "lsat::lr::inference": 0.09,
    "lsat::lr::main_conclusion": 0.04,
    "lsat::lr::method_of_reasoning": 0.04,
    "lsat::lr::parallel_reasoning": 0.04,
    "lsat::lr::principle": 0.05,
    "lsat::lr::paradox": 0.04,
    "lsat::lr::point_at_issue": 0.02,
    "lsat::lr::role_in_argument": 0.03,
    "lsat::lr::evaluate": 0.02,
    "lsat::rc::main_point": 0.06,
    "lsat::rc::primary_purpose": 0.06,
    "lsat::rc::inference": 0.08,
    "lsat::rc::detail": 0.05,
    "lsat::rc::author_attitude": 0.04,
    "lsat::rc::function": 0.03,
}


def _wilson(correct: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = correct / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, center - margin), min(1.0, center + margin))


def _confidence(n: int) -> str:
    if n >= 200:
        return "high"
    if n >= 50:
        return "medium"
    if n >= 1:
        return "low"
    return "none"


def _accuracy(col, card_ids: list[int]) -> tuple[int, int]:
    """(correct, graded) over the revlog of the given cards. Again=1 wrong;
    Hard/Good/Easy=2..4 correct; manual reschedules (0) ignored."""
    if not card_ids:
        return (0, 0)
    ids = ",".join(str(int(c)) for c in card_ids)
    rows = col.db.all(
        f"select ease from revlog where cid in ({ids}) and ease between 1 and 4"
    )
    return (sum(1 for (e,) in rows if e >= 2), len(rows))


def _best_next(col) -> str | None:
    """Top skill to study, from the Rust skill-weakness queue (weakness x weight)."""
    try:
        deck_id = col.decks.id(DECK)
        entries = list(
            col._backend.get_skill_weakness_queue(
                deck_id=deck_id, skill_weights=SKILL_WEIGHTS
            )
        )
    except Exception:
        return None
    best = None
    for e in entries:
        if best is None or e.priority > best.priority:
            best = e
    if best is None or not best.skill:
        return None
    return best.skill.split("::")[-1].replace("_", " ")


def compute(col) -> dict:
    all_cards = list(col.find_cards(f"deck:{DECK}"))
    practice = list(col.find_cards(f'deck:{DECK} "tag:{PRACTICE_TAG}"'))
    m_c, m_n = _accuracy(col, all_cards)
    p_c, p_n = _accuracy(col, practice)
    # Weighted coverage: the heavily-tested (and internally similar) LR skills
    # count for more than a rare skill, so you need not cover every skill/section
    # to project a score.
    covered_tags = [t for t in SKILL_WEIGHTS if col.find_cards(f'deck:{DECK} "tag:{t}"')]
    covered = len(covered_tags)
    total_w = sum(SKILL_WEIGHTS.values())
    covered_w = sum(SKILL_WEIGHTS[t] for t in covered_tags)
    coverage = covered_w / total_w if total_w else 0.0

    missing = []
    if p_n < MIN_PERFORMANCE_ATTEMPTS:
        missing.append(
            f"need &ge; {MIN_PERFORMANCE_ATTEMPTS} graded practice attempts (have {p_n})"
        )
    if coverage < MIN_COVERAGE:
        missing.append(
            f"need &ge; {int(MIN_COVERAGE * 100)}% weighted coverage (have {coverage * 100:.0f}%)"
        )

    return {
        "has_deck": bool(all_cards),
        "memory": (_wilson(m_c, m_n), m_n),
        "performance": (_wilson(p_c, p_n), p_n),
        "coverage": (coverage, covered, len(SKILL_WEIGHTS)),
        "gave_up": bool(missing),
        "missing": missing,
        "next_best": _best_next(col),
    }


def _render(data: dict) -> str:
    if not data["has_deck"]:
        return (
            "<h3>Speedrun LSAT — Readiness</h3>"
            f"<p>No cards found in the <b>{DECK}</b> deck. Import the LSAT deck first.</p>"
        )

    (mp, mlo, mhi), mn = data["memory"]
    (pp, plo, phi), pn = data["performance"]
    cov, ck, ct = data["coverage"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    mem = (
        "no data yet (0 reviews)"
        if mn == 0
        else f"<b>{mp*100:.0f}%</b> recall &nbsp;(range {mlo*100:.0f}&ndash;{mhi*100:.0f}%) "
        f"over {mn} reviews &middot; confidence: {_confidence(mn)}"
    )
    perf = (
        "no data yet (0 graded practice attempts)"
        if pn == 0
        else f"<b>{pp*100:.0f}%</b> &nbsp;(range {plo*100:.0f}&ndash;{phi*100:.0f}%) "
        f"over {pn} attempts &middot; confidence: {_confidence(pn)}"
    )

    if data["gave_up"]:
        readiness = (
            "<b>NOT ENOUGH DATA</b> &mdash; "
            + "; ".join(data["missing"])
            + ".<br><i>A good system knows when it does not know.</i>"
        )
    else:
        point = 120 + pp * 60
        lo = 120 + plo * 60
        hi = 120 + phi * 60
        readiness = (
            f"<b>Projected {point:.0f}</b> &nbsp;(likely range {lo:.0f}&ndash;{hi:.0f}) "
            f"&middot; confidence: {_confidence(pn)}"
        )

    nxt = data["next_best"] or "study any concept to begin"

    return f"""
    <h3>Speedrun LSAT &mdash; Readiness (honest)</h3>
    <p style="color:#888">as of {now}</p>
    <p><b>Memory</b> &mdash; can you recall the fact now?<br>
       {mem}<br><span style="color:#888">recall success rate on graded reviews (FSRS-tracked)</span></p>
    <p><b>Performance</b> &mdash; can you answer a new exam-style question?<br>
       {perf}<br><span style="color:#888">accuracy on practice / exam-style cards</span></p>
    <p><b>Readiness</b> &mdash; what score today, how sure?<br>
       {readiness}</p>
    <hr>
    <p><b>Coverage:</b> {cov*100:.0f}% of exam weight &nbsp;({ck}/{ct} skills)</p>
    <p><b>Best next thing to study:</b> {nxt}</p>
    <p style="color:#888"><b>Give-up rule:</b> no readiness score until
       &ge; {MIN_PERFORMANCE_ATTEMPTS} graded practice attempts AND
       &ge; {int(MIN_COVERAGE*100)}% of exam weight covered. Every number shows
       its range, not a single figure.</p>
    """


class ScoresDialog(QDialog):
    def __init__(self, mw) -> None:
        super().__init__(mw)
        self.setWindowTitle("Speedrun LSAT — Readiness")
        self.resize(520, 560)
        layout = QVBoxLayout(self)

        label = QLabel(_render(compute(mw.col)))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.addWidget(label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


def show_scores(mw) -> None:
    if mw.col is None:
        return
    ScoresDialog(mw).exec()
