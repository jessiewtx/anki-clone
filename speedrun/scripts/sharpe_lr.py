"""Shared definition of the Sharpe interactive elimination card ("Sharpe LR").

Build-time module (no runtime AI). It defines a custom Anki note type whose
card template lets the student *eliminate* answer choices, then on reveal shows
which trap each wrong choice uses and highlights the trap that tempted them
(a wrong answer they failed to eliminate).

Used by:
  - build_deck.py  -> portable .apkg (desktop + AnkiDroid)
  - load_gym.py    -> the live Sharpe collection

The template keeps per-attempt state on ``window.__sharpe`` so the student's
eliminations survive the question->answer flip (same webview, no server, no AI).
"""

import base64
import html
import json

MODEL_NAME = "Sharpe LR"
LETTERS = ["A", "B", "C", "D", "E", "F", "G"]

FIELDS = [
    "QID", "Skill", "Difficulty", "Stimulus", "Question",
    "ChoicesHTML", "AnswerIndex", "TrapsB64", "Explanation",
]

# Canonical 9-trap taxonomy (matches speedrun/scripts/check_bank.py).
# id -> (friendly name, one-line "why it's a trap")
TRAP_INFO = {
    "out_of_scope": ("Out of scope", "It brings in something the argument never addresses."),
    "too_strong": ("Too strong", "It overstates with absolute words like all, only, or never."),
    "reversal": ("Reversal", "It flips the direction of the relationship or conditional."),
    "half_right": ("Half right", "It starts correctly but breaks on a key detail."),
    "correlation_causation": ("Correlation \u2260 causation", "It treats things that occur together as cause and effect."),
    "could_be_true": ("Could be true \u2260 must be true", "It is possible, but not required by the statements."),
    "restates_premise": ("Restates a premise", "It repeats given information instead of drawing the conclusion."),
    "plausible_unsupported": ("Plausible but unsupported", "It sounds reasonable, but the stimulus never backs it."),
    "shifted_subject": ("Shifted subject", "It changes who or what is being compared."),
}

SKILL_NAMES = {
    "flaw": "Flaw",
    "weaken": "Weaken",
    "strengthen": "Strengthen",
    "necessary_assumption": "Necessary assumption",
    "sufficient_assumption": "Sufficient assumption",
    "inference": "Inference",
    "main_conclusion": "Main conclusion",
    "method_of_reasoning": "Method of reasoning",
    "principle": "Principle",
    "parallel": "Parallel reasoning",
    "paradox": "Paradox",
    "point_at_issue": "Point at issue",
    "role": "Role in argument",
    "evaluate": "Evaluate the argument",
}

CSS = """
.card { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #ffffff; }
.sharpe-lr { max-width: 640px; margin: 0 auto; text-align: left; color: #1a1a2e; font-size: 17px; line-height: 1.5; }
.sharpe-lr .hdr { font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: #F47A38; margin-bottom: 10px; }
.sharpe-lr .stim { margin: 6px 0 2px; }
.sharpe-lr .qst { font-weight: 700; margin: 12px 0 10px; }
.sharpe-lr .choice { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 10px; padding: 10px 12px; border: 1.5px solid #e3e3ea; border-radius: 12px; margin: 8px 0; cursor: pointer; transition: border-color .12s, background .12s; }
.sharpe-lr .choice:hover { border-color: #F47A38; }
.sharpe-lr .choice .lc { flex: 0 0 auto; width: 26px; height: 26px; border-radius: 50%; background: #f1f1f6; color: #333; font-weight: 800; font-size: 14px; display: inline-flex; align-items: center; justify-content: center; }
.sharpe-lr .choice .ct { flex: 1; min-width: 0; }
.sharpe-lr .choice.elim { opacity: .55; background: #fafafb; }
.sharpe-lr .choice.elim .ct { text-decoration: line-through; }
.sharpe-lr .choice.correct { border-color: #2e9e5b; background: #edfbf2; }
.sharpe-lr .choice.correct .lc { background: #2e9e5b; color: #fff; }
.sharpe-lr .choice.good { border-color: #2e9e5b; }
.sharpe-lr .choice.good .lc { background: #2e9e5b; color: #fff; }
.sharpe-lr .choice.bad { border-color: #d64545; background: #fdefef; }
.sharpe-lr .choice.bad .lc { background: #d64545; color: #fff; }
.sharpe-lr .verdict { flex-basis: 100%; margin: 4px 0 0 36px; font-size: 13px; color: #555; }
.sharpe-lr .hint { margin-top: 12px; font-size: 13px; font-style: italic; color: #8a8a93; }
.sharpe-lr .banner { margin-top: 16px; padding: 11px 14px; border-radius: 12px; font-weight: 700; }
.sharpe-lr .banner.win { background: #edfbf2; color: #1e7a45; }
.sharpe-lr .banner.miss { background: #fdefef; color: #a5302f; }
.explanation { max-width: 640px; margin: 16px auto 0; text-align: left; color: #333; font-size: 15px; border-top: 1px solid #ececf0; padding-top: 12px; }
.explanation .ex-h { display: block; font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: #F47A38; margin-bottom: 4px; }
"""

_FRONT = """<div class="sharpe-lr" data-qid="{{QID}}">
  <div class="hdr">{{Skill}} &middot; Difficulty {{Difficulty}}</div>
  <div class="stim">{{Stimulus}}</div>
  <div class="qst">{{Question}}</div>
  <div class="choices">{{ChoicesHTML}}</div>
  <div class="hint">Tap the answers you can rule out &mdash; what's left is your pick, then flip.</div>
</div>
<script>
(function () {
  var root = document.querySelector('.sharpe-lr');
  if (!root) return;
  var qid = root.getAttribute('data-qid');
  var store = (window.__sharpe = window.__sharpe || {});
  var choices = Array.prototype.slice.call(root.querySelectorAll('.choice'));
  var dataEl = document.getElementById('sharpe-data');
  var TRAP = __TRAPJSON__;
  function pretty(id) { return (id || '').replace(/_/g, ' ').replace(/\\b\\w/g, function (c) { return c.toUpperCase(); }); }

  if (!dataEl) {
    // FRONT: begin a fresh attempt for this question
    store[qid] = { elim: {} };
    choices.forEach(function (el) {
      el.classList.remove('elim', 'correct', 'good', 'bad');
      el.addEventListener('click', function () {
        var i = el.getAttribute('data-i');
        var st = store[qid] || (store[qid] = { elim: {} });
        if (st.elim[i]) { delete st.elim[i]; el.classList.remove('elim'); }
        else { st.elim[i] = 1; el.classList.add('elim'); }
      });
    });
    return;
  }

  // BACK: reveal + score the elimination
  var st = store[qid] || { elim: {} };
  var answer = parseInt(dataEl.getAttribute('data-answer'), 10);
  var traps = [];
  try { traps = JSON.parse(atob(dataEl.getAttribute('data-traps'))); } catch (e) {}
  var tempted = [], temptedIds = [], elimCorrect = false;

  choices.forEach(function (el) {
    var i = parseInt(el.getAttribute('data-i'), 10);
    var eliminated = !!st.elim[String(i)];
    if (eliminated) el.classList.add('elim');
    var v = document.createElement('div');
    v.className = 'verdict';
    if (i === answer) {
      el.classList.add('correct');
      if (eliminated) { el.classList.add('bad'); elimCorrect = true; v.innerHTML = '\u2717 This was the correct answer \u2014 you ruled it out.'; }
      else { v.innerHTML = '\u2713 Correct answer.'; }
    } else {
      var tid = traps[i];
      var info = tid && TRAP[tid] ? TRAP[tid] : null;
      var label = info ? info.name : (pretty(tid) || 'Wrong');
      var why = info ? info.why : '';
      if (eliminated) { el.classList.add('good'); v.innerHTML = '\u2713 Ruled out \u2014 <b>' + label + '</b>. ' + why; }
      else { el.classList.add('bad'); v.innerHTML = '\u26a0 You left this in \u2014 <b>' + label + '</b> tempted you. ' + why; tempted.push(label); temptedIds.push(tid || 'unknown'); }
    }
    el.appendChild(v);
  });

  var b = document.createElement('div');
  b.className = 'banner';
  if (!elimCorrect && tempted.length === 0) {
    b.classList.add('win');
    b.innerHTML = '\U0001F3AF Clean elimination \u2014 you cut every trap.';
  } else {
    b.classList.add('miss');
    var msg = [];
    if (elimCorrect) msg.push('you ruled out the correct answer');
    if (tempted.length) msg.push('tempted by ' + tempted.join(', '));
    b.innerHTML = '\u2717 ' + msg.join(' \u00b7 ');
  }
  root.appendChild(b);

  // Report the attempt to Python if a bridge is present (added in a later step).
  try { if (window.pycmd) window.pycmd('sharpe:attempt:' + JSON.stringify({ qid: qid, tempted: temptedIds, elimCorrect: elimCorrect, clean: (!elimCorrect && temptedIds.length === 0) })); } catch (e) {}
})();
</script>"""

_BACK = """{{FrontSide}}
<div id="sharpe-data" data-answer="{{AnswerIndex}}" data-traps="{{TrapsB64}}" style="display:none"></div>
<div class="explanation"><span class="ex-h">Why</span>{{Explanation}}</div>"""


def _trap_js() -> str:
    return json.dumps({k: {"name": v[0], "why": v[1]} for k, v in TRAP_INFO.items()})


FRONT_HTML = _FRONT.replace("__TRAPJSON__", _trap_js())
BACK_HTML = _BACK


def skill_name(card: dict) -> str:
    for t in card.get("tags", []):
        if t.startswith("lsat::lr::"):
            k = t.split("::")[-1]
            return SKILL_NAMES.get(k, k.replace("_", " ").capitalize())
    return "Logical Reasoning"


def build_choices_html(choices: list[str]) -> str:
    return "".join(
        '<div class="choice" data-i="%d"><span class="lc">%s</span><span class="ct">%s</span></div>'
        % (i, LETTERS[i], html.escape(c))
        for i, c in enumerate(choices)
    )


def traps_b64(traps: list) -> str:
    return base64.b64encode(json.dumps(traps).encode("utf-8")).decode("ascii")


def ensure_model(col):
    """Create or refresh the Sharpe LR note type in the given collection."""
    mm = col.models
    m = mm.by_name(MODEL_NAME)
    if m is None:
        m = mm.new(MODEL_NAME)
        for f in FIELDS:
            mm.add_field(m, mm.new_field(f))
        t = mm.new_template("Elimination")
        t["qfmt"] = FRONT_HTML
        t["afmt"] = BACK_HTML
        mm.add_template(m, t)
        m["css"] = CSS
        mm.add(m)
    else:
        # Refresh template/css so edits to this module take effect on re-run.
        m["css"] = CSS
        m["tmpls"][0]["qfmt"] = FRONT_HTML
        m["tmpls"][0]["afmt"] = BACK_HTML
        mm.update_dict(m)
    return mm.by_name(MODEL_NAME)


def populate(note, card: dict) -> None:
    note["QID"] = card["id"]
    note["Skill"] = skill_name(card)
    note["Difficulty"] = str(card.get("difficulty", ""))
    note["Stimulus"] = card.get("stimulus", "")
    note["Question"] = card["question"]
    note["ChoicesHTML"] = build_choices_html(card["choices"])
    note["AnswerIndex"] = str(card["answerIndex"])
    note["TrapsB64"] = traps_b64(card.get("choiceTraps", [None] * len(card["choices"])))
    note["Explanation"] = card["explanation"]


def trap_tags(card: dict) -> list[str]:
    """`trap::<id>` tags for the distinct wrong-answer traps this card contains,
    so the Rust weakness queue can treat traps as first-class 'skills'."""
    traps = card.get("choiceTraps") or []
    return sorted({f"trap::{t}" for t in traps if t})


# --- standalone preview helpers (used by preview_gym.py) ---

def render_front(card: dict) -> str:
    h = FRONT_HTML
    h = h.replace("{{QID}}", card["id"])
    h = h.replace("{{Skill}}", skill_name(card))
    h = h.replace("{{Difficulty}}", str(card.get("difficulty", "")))
    h = h.replace("{{Stimulus}}", card.get("stimulus", ""))
    h = h.replace("{{Question}}", card["question"])
    h = h.replace("{{ChoicesHTML}}", build_choices_html(card["choices"]))
    return h


def render_back(card: dict) -> str:
    h = BACK_HTML.replace("{{FrontSide}}", render_front(card))
    h = h.replace("{{AnswerIndex}}", str(card["answerIndex"]))
    h = h.replace("{{TrapsB64}}", traps_b64(card.get("choiceTraps", [None] * len(card["choices"]))))
    h = h.replace("{{Explanation}}", card["explanation"])
    return h
