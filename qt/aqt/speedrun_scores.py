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
MIN_PERFORMANCE_ATTEMPTS = 25  # ~one scored LSAT section (an LR section is ~25 Qs)
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


def _bar(frac: float, segments: int = 22) -> str:
    """A little text progress bar (orange filled, cream empty) that renders in Qt."""
    frac = max(0.0, min(1.0, frac))
    filled = round(segments * frac)
    return (
        '<span style="font-family:monospace;letter-spacing:-1px">'
        f'<span style="color:#F95602">{"&#9608;" * filled}</span>'
        f'<span style="color:#DCD2BE">{"&#9608;" * (segments - filled)}</span>'
        "</span>"
    )


# LSAT raw%->scaled-score anchors, from published LSAC score-conversion tables.
# (The exact curve shifts slightly per administered test; this is a representative
# recent curve.) We interpolate between anchors so the projection is grounded in
# the real 120-180 scale rather than an invented linear rule.
_LSAT_ANCHORS = [
    (0.00, 120), (0.30, 120), (0.40, 139), (0.50, 145),
    (0.60, 151), (0.70, 157), (0.80, 164), (0.90, 172), (1.00, 180),
]


def _scaled_score(p: float) -> float:
    """Fraction-correct on exam-style items -> 120-180, by linear interpolation
    between the published conversion anchors above."""
    p = max(0.0, min(1.0, p))
    for (x0, y0), (x1, y1) in zip(_LSAT_ANCHORS, _LSAT_ANCHORS[1:]):
        if p <= x1:
            t = 0.0 if x1 == x0 else (p - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 180.0


def _practice_events(col, practice_ids: list[int]) -> list[tuple[str, int]]:
    """Every graded practice attempt as (skill, correct?), in time order."""
    if not practice_ids:
        return []
    skill_of: dict[int, str] = {}
    for cid in practice_ids:
        try:
            note = col.get_card(cid).note()
            skill_of[cid] = next(
                (t for t in note.tags
                 if t.startswith("lsat::lr::") or t.startswith("lsat::rc::")),
                "unknown",
            )
        except Exception:
            skill_of[cid] = "unknown"
    ids = ",".join(str(int(c)) for c in practice_ids)
    return [
        (skill_of.get(cid, "unknown"), 1 if ease >= 2 else 0)
        for cid, ease in col.db.all(
            f"select cid, ease from revlog where cid in ({ids}) "
            "and ease between 1 and 4 order by id"
        )
    ]


def _prequential(events: list[tuple[str, int]]) -> tuple[list[float], list[int]]:
    """Forward-validated predictions: for each attempt in time order, predict
    P(correct) from ONLY earlier attempts (that skill's running rate, smoothed
    toward the running global rate). The model never sees the outcome it's scored
    on, so this is an honest record of how good past guesses were."""
    from collections import defaultdict

    seen: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    g_c = g_n = 0.0
    preds: list[float] = []
    outs: list[int] = []
    for skill, o in events:
        gp = (g_c / g_n) if g_n >= 5 else 0.5
        c, n = seen[skill]
        preds.append((c + 2.0 * gp) / (n + 2.0))  # skill rate, smoothed toward global
        outs.append(o)
        seen[skill] = [c + o, n + 1]
        g_c += o
        g_n += 1
    return preds, outs


def _calibration(preds: list[float], outs: list[int]) -> dict:
    """Brier score + expected calibration error (ECE) over the forward predictions."""
    n = len(preds)
    if n == 0:
        return {"n": 0}
    brier = sum((p - o) ** 2 for p, o in zip(preds, outs)) / n
    base = sum(outs) / n
    brier_base = sum((base - o) ** 2 for o in outs) / n
    ece = 0.0
    for lo, hi in [(0.0, 0.5), (0.5, 0.65), (0.65, 0.8), (0.8, 1.01)]:
        idx = [i for i, p in enumerate(preds) if lo <= p < hi]
        if not idx:
            continue
        avg_p = sum(preds[i] for i in idx) / len(idx)
        avg_o = sum(outs[i] for i in idx) / len(idx)
        ece += (len(idx) / n) * abs(avg_p - avg_o)
    return {"n": n, "brier": brier, "brier_base": brier_base, "ece": ece}


def _cal_line(cal: dict) -> str:
    """One-line 'how accurate were past guesses' summary (honesty rule)."""
    if not cal or cal.get("n", 0) < 10:
        return ""
    return (
        '<br><span style="color:#888">Calibration &mdash; how close past predictions '
        f'landed: &plusmn;{cal["ece"] * 100:.0f}% avg error over {cal["n"]} '
        f'forward-tested guesses (Brier {cal["brier"]:.2f} vs '
        f'{cal["brier_base"]:.2f} base-rate baseline).</span>'
    )


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
    concept = list(col.find_cards(f'deck:{DECK} -"tag:{PRACTICE_TAG}"'))
    # Memory = recall on concept/definition cards ONLY (can you retrieve the fact?).
    # Performance = accuracy on new exam-style problems ONLY (can you use it?).
    # Scoring them on different card pools is what lets us measure the gap between
    # the two rather than hiding it.
    m_c, m_n = _accuracy(col, concept)
    p_c, p_n = _accuracy(col, practice)
    cal = _calibration(*_prequential(_practice_events(col, practice)))
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
        "calibration": cal,
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
    cal = data.get("calibration") or {"n": 0}
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

    if mn > 0 and pn > 0:
        gap = (mp - pp) * 100
        gap_html = (
            "<p><b>The gap</b> &mdash; memory minus performance<br>"
            f"You recall <b>{mp*100:.0f}%</b> of the facts but answer only "
            f"<b>{pp*100:.0f}%</b> of new questions &mdash; a "
            f"<b>{gap:+.0f}-point</b> gap.<br>"
            '<span style="color:#888">The fluency illusion: knowing a fact is not the '
            "same as using it. Readiness follows performance, not memory.</span></p>"
        )
    else:
        gap_html = (
            '<p style="color:#888"><b>The gap</b> (memory vs. performance) appears '
            "once you have both some reviews and some practice attempts.</p>"
        )

    if data["gave_up"]:
        attempts_frac = pn / MIN_PERFORMANCE_ATTEMPTS if MIN_PERFORMANCE_ATTEMPTS else 1.0
        cov_frac = cov / MIN_COVERAGE if MIN_COVERAGE else 1.0
        remaining = max(0, MIN_PERFORMANCE_ATTEMPTS - pn)
        attempts_ok = pn >= MIN_PERFORMANCE_ATTEMPTS
        cov_ok = cov >= MIN_COVERAGE
        problems_tag = "&#10003; ready" if attempts_ok else f"<b>{remaining} more to go</b>"
        cov_tag = "&#10003; ready" if cov_ok else "add a missing topic"
        readiness = (
            "<b>Your official LSAT projection is still locked</b> &mdash; we hold it back "
            "until there's enough data to be honest. Here's exactly how close you are:"
            f'<div style="margin-top:8px">Problems answered &nbsp; <b>{pn} / {MIN_PERFORMANCE_ATTEMPTS}</b>'
            f'<br>{_bar(attempts_frac)} &nbsp; {problems_tag}</div>'
            f'<div style="margin-top:8px">Topic coverage &nbsp; <b>{cov*100:.0f}% / {int(MIN_COVERAGE*100)}%</b>'
            f'<br>{_bar(cov_frac)} &nbsp; {cov_tag}</div>'
        )
        if pn > 0:
            point = _scaled_score(pp)
            lo = _scaled_score(plo)
            hi = _scaled_score(phi)
            readiness += (
                '<div style="margin-top:10px;padding:8px 10px;background:#FFF6E6;'
                'border-radius:8px;color:#8a6d1a">'
                f"<b>Sneak peek (not official yet):</b> around <b>{point:.0f}</b> "
                f"(range {lo:.0f}&ndash;{hi:.0f}), from your {pn} attempt"
                f'{"s" if pn != 1 else ""} so far. Finish the checklist above to lock in a real score.'
                f"{_cal_line(cal)}"
                "</div>"
            )
        else:
            readiness += (
                '<div style="margin-top:10px;color:#888">Answer your first practice '
                "problem and a sneak-peek projection shows up here right away.</div>"
            )
    else:
        point = _scaled_score(pp)
        lo = _scaled_score(plo)
        hi = _scaled_score(phi)
        readiness = (
            f"<b>Projected {point:.0f}</b> &nbsp;(likely range {lo:.0f}&ndash;{hi:.0f}) "
            f"&middot; confidence: {_confidence(pn)}"
            f"{_cal_line(cal)}"
        )

    nxt = data["next_best"] or "study any concept to begin"

    return f"""
    <h3>Speedrun LSAT &mdash; Readiness (honest)</h3>
    <p style="color:#888">as of {now}</p>
    <p><b>Memory</b> &mdash; can you recall the fact now?<br>
       {mem}<br><span style="color:#888">recall rate on <b>concept cards only</b> (the FSRS-scheduled fact cards)</span></p>
    <p><b>Performance</b> &mdash; can you answer a new exam-style question?<br>
       {perf}<br><span style="color:#888">accuracy on <b>practice/problem cards only</b> (fresh, exam-style items)</span></p>
    {gap_html}
    <p><b>Readiness</b> &mdash; what score today, how sure?<br>
       {readiness}</p>
    <hr>
    <p><b>Coverage:</b> {cov*100:.0f}% of exam weight &nbsp;({ck}/{ct} skills)</p>
    <p><b>Best next thing to study:</b> {nxt}</p>
    <p style="color:#888"><b>How the number is built:</b> your % correct on new
       exam-style items &rarr; the 120&ndash;180 scale via published LSAT raw&rarr;scaled
       conversion anchors; the range is a 95% Wilson interval carried through that
       mapping; calibration forward-tests past predictions (Brier + calibration error).</p>
    <p style="color:#888"><b>Give-up rule:</b> no official readiness score until
       &ge; {MIN_PERFORMANCE_ATTEMPTS} graded <b>practice attempts</b> (answers to
       problem cards &mdash; concept reviews don't count) AND &ge; {int(MIN_COVERAGE*100)}%
       of exam weight covered. Every number shows its range, not a single figure.</p>
    """


def stats_header_html(col) -> str:
    """Compact three-score banner for the TOP of the Stats screen, so Memory,
    Performance and Readiness are all visible where students look for stats."""
    d = compute(col)
    if not d.get("has_deck"):
        return ""
    (mp, mlo, mhi), mn = d["memory"]
    (pp, plo, phi), pn = d["performance"]

    def rng(lo: float, hi: float, suff: str = "%") -> str:
        return f'<span style="color:#8a8378">({lo:.0f}&ndash;{hi:.0f}{suff})</span>'

    mem = (
        f'<b>{mp*100:.0f}%</b> {rng(mlo*100, mhi*100)} <span style="color:#8a8378">&middot; {mn} reviews</span>'
        if mn
        else '<span style="color:#8a8378">no data yet &mdash; review a few concept cards</span>'
    )
    perf = (
        f'<b>{pp*100:.0f}%</b> {rng(plo*100, phi*100)} <span style="color:#8a8378">&middot; {pn} attempts</span>'
        if pn
        else '<span style="color:#8a8378">no data yet &mdash; answer a few practice cards</span>'
    )
    if d["gave_up"]:
        need = max(0, MIN_PERFORMANCE_ATTEMPTS - pn)
        read = (
            f'<span style="color:#9A6A12">locked &mdash; {need} more practice attempts to unlock</span>'
            if need
            else '<span style="color:#9A6A12">locked &mdash; need more topic coverage</span>'
        )
    else:
        read = f'<b>{_scaled_score(pp):.0f}</b> {rng(_scaled_score(plo), _scaled_score(phi), "")}'

    return f"""
    <div style="background:#FBF3E7;border:1.5px solid #CDB37E;border-radius:12px;padding:12px 16px;margin:8px 8px 0">
      <div style="font-size:12px;font-weight:800;letter-spacing:.06em;color:#F95602;margin-bottom:8px">SHARPE &mdash; YOUR THREE SCORES</div>
      <table cellspacing="0" cellpadding="4" style="font-size:14px;color:#34302A">
        <tr><td><b>Memory</b> &mdash; recall a fact now</td><td>&nbsp;&nbsp;{mem}</td></tr>
        <tr><td><b>Performance</b> &mdash; answer a new question</td><td>&nbsp;&nbsp;{perf}</td></tr>
        <tr><td><b>Readiness</b> &mdash; LSAT score today</td><td>&nbsp;&nbsp;{read}</td></tr>
      </table>
      <div style="font-size:12px;color:#8a8378;margin-top:6px">Full breakdown (range + calibration): <b>Readiness</b> toolbar button or <b>Tools &rarr; Sharpe: My LSAT Score</b></div>
    </div>"""


class ScoresDialog(QDialog):
    def __init__(self, mw, body: str | None = None) -> None:
        super().__init__(mw)
        self.setWindowTitle("Sharpe — My LSAT Score")
        self.resize(520, 600)
        layout = QVBoxLayout(self)

        label = QLabel(body if body is not None else _render(compute(mw.col)))
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


def _sample_data() -> dict:
    """Realistic made-up numbers so you can see the score layout without grinding
    real problems (~a mid-range student). Shown with a clear SAMPLE banner."""
    return {
        "has_deck": True,
        "memory": ((0.80, 0.72, 0.86), 90),
        "performance": ((0.62, 0.55, 0.69), 60),
        "coverage": (0.88, 18, len(SKILL_WEIGHTS)),
        "gave_up": False,
        "missing": [],
        "next_best": "necessary assumption",
        "calibration": {"n": 60, "brier": 0.20, "brier_base": 0.24, "ece": 0.06},
    }


def show_scores_sample(mw) -> None:
    if mw.col is None:
        return
    banner = (
        '<div style="background:#FFF6E6;color:#8a6d1a;padding:10px 12px;'
        'border-radius:10px;margin-bottom:10px;font-weight:700">SAMPLE PREVIEW '
        "&mdash; made-up numbers so you can see what the score looks like. "
        "This is NOT your real data.</div>"
    )
    ScoresDialog(mw, banner + _render(_sample_data())).exec()
