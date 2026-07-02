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

# Student-facing broad families. The LSAT never asks you to name a micro-flaw, so
# students pick one of these; the fine trap above is kept for internal metrics and
# the trap-aware scheduler. Each fine trap maps to exactly one family.
TRAP_FAMILIES = {
    "irrelevant": ("Irrelevant / off-topic", "Brings in something the argument isn't about \u2014 a new topic, or the wrong subject/group."),
    "too_strong": ("Too strong", "Overstates \u2014 absolute words (all, only, never) or a claim bigger than the evidence."),
    "distorts_logic": ("Distorts the logic", "Reverses the relationship, or treats correlation as causation."),
    "unsupported": ("Unsupported / doesn't follow", "Sounds plausible, but the stimulus doesn't prove it \u2014 only possible, partly right, or just restates a premise."),
}

FINE_TO_FAMILY = {
    "out_of_scope": "irrelevant",
    "shifted_subject": "irrelevant",
    "too_strong": "too_strong",
    "reversal": "distorts_logic",
    "correlation_causation": "distorts_logic",
    "plausible_unsupported": "unsupported",
    "could_be_true": "unsupported",
    "restates_premise": "unsupported",
    "half_right": "unsupported",
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
.sharpe-lr .hdr { font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: #F95602; margin-bottom: 10px; }
.sharpe-lr .stim { margin: 6px 0 2px; }
.sharpe-lr .qst { font-weight: 700; margin: 12px 0 10px; }
.sharpe-lr .choice { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 10px; padding: 10px 12px; border: 1.5px solid #e3e3ea; border-radius: 12px; margin: 8px 0; cursor: pointer; transition: border-color .12s, background .12s; }
.sharpe-lr .choice:hover { border-color: #F95602; }
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
.explanation .ex-h { display: block; font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: #F95602; margin-bottom: 4px; }
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


def _family_js() -> str:
    families = {k: {"name": v[0], "why": v[1]} for k, v in TRAP_FAMILIES.items()}
    fine = {
        f: {"name": TRAP_INFO.get(f, (f.replace("_", " ").capitalize(), ""))[0], "family": fam}
        for f, fam in FINE_TO_FAMILY.items()
    }
    return json.dumps({"families": families, "fine": fine})


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


# ======================================================================
# Mode 1 — "Trap Spotter": judge ONE choice (Right / Wrong -> which flaw?).
# The simplest, lowest-overload interaction; the elimination card above is the
# advanced stage. One note per (question, choice).
# ======================================================================

MODEL_JUDGE = "Sharpe Judge"
FIELDS_JUDGE = [
    "QID", "Skill", "Difficulty", "Stimulus", "Question",
    "ChoiceLetter", "Choice", "Verdict", "Trap", "Explanation",
    # Precomputed so the answer side is fully static (renders on desktop + phone
    # without depending on JS state, which AnkiDroid drops on the card flip).
    "IsCorrect", "FamilyName", "FamilyWhy", "FineName",
]

JUDGE_CSS = """
.card { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #FBF5EC; padding: 8px 18px 24px; }
.sharpe-judge { max-width: 640px; margin: 0 auto; text-align: left; color: #34302A; font-size: 17px; line-height: 1.55; }
.sharpe-judge .hdr { font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: #F95602; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1.5px solid #CDB37E; }
.sharpe-judge .stim { margin: 6px 0 2px; }
.sharpe-judge .qst { font-weight: 700; margin: 12px 0 12px; color: #2C2822; }
.sharpe-judge .one-choice { display: flex; gap: 10px; align-items: flex-start; padding: 16px; border: 1.5px solid #D4BC84; border-radius: 14px; margin: 6px 0 18px; background: #FFFFFF; box-shadow: 0 2px 10px rgba(139, 94, 42, .06); }
.sharpe-judge .one-choice .lc { flex: 0 0 auto; width: 27px; height: 27px; border-radius: 50%; background: #B09862; color: #2C2822; font-weight: 800; display: inline-flex; align-items: center; justify-content: center; }
.sharpe-judge .one-choice .ct { flex: 1; min-width: 0; }
.sharpe-judge .ask { font-weight: 700; margin: 0 0 10px; }
.sharpe-judge .judge-btns { display: flex; gap: 12px; }
.sharpe-judge .jb { flex: 1; padding: 13px; border: 1.5px solid #EADBC6; border-radius: 14px; background: #FFFFFF; font-weight: 800; font-size: 16px; color: #34302A; cursor: pointer; transition: all .12s; }
.sharpe-judge .jb.yes:hover { border-color: #3AA76D; background: #EEF8F1; }
.sharpe-judge .jb.no:hover { border-color: #E0673A; background: #FCEEE4; }
.sharpe-judge .jb.sel { background: #F95602; color: #fff; border-color: #F95602; box-shadow: 0 3px 10px rgba(224, 114, 46, .25); }
.sharpe-judge .trap-pick { margin-top: 16px; }
.sharpe-judge .ask2 { font-weight: 700; margin-bottom: 10px; }
.sharpe-judge .trap-opts { display: flex; flex-wrap: wrap; gap: 8px; }
.sharpe-judge .topt { padding: 9px 14px; border: 1.5px solid #EADBC6; border-radius: 999px; background: #FFFDF9; font-size: 14px; color: #4A4038; cursor: pointer; transition: all .12s; }
.sharpe-judge .topt:hover { border-color: #F95602; background: #FFF3E4; }
.sharpe-judge .topt.sel { background: #F95602; color: #fff; border-color: #F95602; }
.sharpe-judge .topt.correct { border-color: #3AA76D; color: #1E7A45; background: #EEF8F1; font-weight: 700; }
.sharpe-judge .jb.good { border-color: #2e9e5b; background: #EEF8F1; color: #1E7A45; }
.sharpe-judge .jb.bad { border-color: #d64545; background: #FCEEE4; color: #C1502E; }
.sharpe-judge .jb.correct { border-color: #2e9e5b; background: #EEF8F1; color: #1E7A45; }
.sharpe-judge .topt.good { border-color: #2e9e5b; background: #EEF8F1; color: #1E7A45; }
.sharpe-judge .topt.bad { border-color: #d64545; background: #FCEEE4; color: #C1502E; }
.sharpe-judge .result { margin-top: 14px; padding: 11px 14px; border-radius: 12px; font-weight: 700; font-size: 15px; }
.sharpe-judge .result:empty { display: none; }
.sharpe-judge .result.ok { background: #ECF7EF; color: #1E7A45; }
.sharpe-judge .result.bad { background: #FCEEE4; color: #C1502E; }
.sharpe-judge .result.warn { background: #FFF6E6; color: #9A6A12; }
.sharpe-judge .hint { margin-top: 14px; font-size: 13px; font-style: italic; color: #A6907A; }
.sharpe-judge .banner { margin-top: 18px; padding: 12px 15px; border-radius: 14px; font-weight: 700; }
.sharpe-judge .banner.win { background: #ECF7EF; color: #1E7A45; }
.sharpe-judge .banner.miss { background: #FCEEE4; color: #C1502E; }
.sharpe-judge .autohint { margin-top: 8px; font-size: 12px; color: #A6907A; }
.sharpe-judge .fine { color: #A6907A; font-weight: 400; }
.explanation { max-width: 640px; margin: 18px auto 0; text-align: left; color: #4A4038; font-size: 15px; border-top: 1.5px solid #CDB37E; padding-top: 14px; }
.explanation .ex-h { display: block; font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: #F95602; margin-bottom: 4px; }
.nightMode.card { background: #241F1A; }
.nightMode .sharpe-judge { color: #EDE3D5; }
.nightMode .sharpe-judge .qst { color: #F3EADC; }
.nightMode .sharpe-judge .one-choice, .nightMode .sharpe-judge .jb, .nightMode .sharpe-judge .topt { background: #2E2822; border-color: #463A2E; color: #EDE3D5; }
.nightMode .explanation { color: #D9CDBC; border-top-color: #463A2E; }
.reveal { max-width: 640px; margin: 16px auto 0; padding: 12px 15px; border-radius: 14px; font-weight: 700; font-size: 15px; line-height: 1.5; }
.reveal.ok { background: #ECF7EF; color: #1E7A45; }
.reveal.trap { background: #FCEEE4; color: #C1502E; }
.reveal .fine { color: #A6907A; font-weight: 400; }
.nightMode .reveal.ok { background: #21402C; color: #8FD6A6; }
.nightMode .reveal.trap { background: #45241A; color: #F0A98C; }
"""

_JUDGE_FRONT = """<div class="sharpe-judge" data-qid="{{QID}}" data-verdict="{{Verdict}}" data-trap="{{Trap}}">
  <div class="hdr">{{Skill}} &middot; Difficulty {{Difficulty}}</div>
  <div class="stim">{{Stimulus}}</div>
  <div class="qst">{{Question}}</div>
  <div class="one-choice"><span class="lc">{{ChoiceLetter}}</span><span class="ct">{{Choice}}</span></div>
  <div class="ask">Is this the correct answer?</div>
  <div class="judge-btns">
    <button class="jb yes" data-j="right">Right</button>
    <button class="jb no" data-j="wrong">Wrong</button>
  </div>
  <div class="trap-pick" style="display:none">
    <div class="ask2">What kind of flaw is it?</div>
    <div class="trap-opts"></div>
  </div>
  <div class="result"></div>
  <div class="hint">Tap Right or Wrong for instant feedback, then flip for the explanation.</div>
</div>
<script>
(function () {
  var root = document.querySelector('.sharpe-judge');
  if (!root) return;
  var qid = root.getAttribute('data-qid');
  var DATA = __FAMILYJSON__;
  var FAM = DATA.families, FINE = DATA.fine;
  var verdict = root.getAttribute('data-verdict');
  var fineId = root.getAttribute('data-trap') || '';
  var flawed = verdict === 'flawed';
  var correctFam = (FINE[fineId] || {}).family || '';
  var pick = root.querySelector('.trap-pick');
  var opts = root.querySelector('.trap-opts');
  var result = root.querySelector('.result');
  var jbs = Array.prototype.slice.call(root.querySelectorAll('.jb'));
  var done = false;

  function say(cls, html) { result.className = 'result ' + cls; result.innerHTML = html; }
  function report(clean, tempted) {
    try { if (window.pycmd) window.pycmd('sharpe:attempt:' + JSON.stringify({ qid: qid, clean: !!clean, tempted: tempted || [] })); } catch (e) {}
  }

  function buildFamilies() {
    opts.innerHTML = '';
    Object.keys(FAM).forEach(function (fid) {
      var b = document.createElement('button');
      b.className = 'topt'; b.setAttribute('data-t', fid); b.textContent = FAM[fid].name;
      b.addEventListener('click', function () {
        if (done) return;
        done = true;
        var ok = fid === correctFam;
        b.classList.add(ok ? 'good' : 'bad');
        if (!ok) { var c = opts.querySelector('[data-t="' + correctFam + '"]'); if (c) c.classList.add('correct'); }
        var nm = (FAM[correctFam] || { name: 'the flaw' }).name;
        if (ok) say('ok', '\U0001F3AF Exactly \u2014 <b>' + nm + '</b>.');
        else say('warn', 'Right call (it\\'s flawed) \u2014 but the flaw is <b>' + nm + '</b>.');
        report(ok, ok ? [] : [fineId]);
      });
      opts.appendChild(b);
    });
  }

  jbs.forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (done) return;
      var j = btn.getAttribute('data-j');
      jbs.forEach(function (x) { x.classList.remove('good', 'bad', 'correct'); });
      if (j === 'wrong' && flawed) {
        btn.classList.add('good');
        pick.style.display = 'block';
        buildFamilies();
        say('ok', '\u2713 Right \u2014 it\\'s flawed. Now: which flaw?');
      } else if (j === 'right' && !flawed) {
        done = true; btn.classList.add('good');
        say('ok', '\u2713 Correct \u2014 this is the credited answer.');
        report(true, []);
      } else if (j === 'right' && flawed) {
        done = true; btn.classList.add('bad');
        var nm = (FAM[correctFam] || { name: 'a trap' }).name;
        say('bad', '\u2717 Trap \u2014 it\\'s <b>' + nm + '</b>, not the credited answer.');
        report(false, [fineId]);
      } else {
        done = true; btn.classList.add('bad');
        var y = root.querySelector('.jb.yes'); if (y) y.classList.add('correct');
        say('bad', '\u2717 This <b>is</b> the credited answer \u2014 you rejected it.');
        report(false, []);
      }
    });
  });
})();
</script>"""

_JUDGE_BACK = """{{FrontSide}}
<div id="sharpe-judge-data" data-verdict="{{Verdict}}" data-trap="{{Trap}}" style="display:none"></div>
{{#IsCorrect}}<div class="reveal ok">\u2713 This is the credited (correct) answer.</div>{{/IsCorrect}}
{{^IsCorrect}}<div class="reveal trap">\u2717 This is a trap \u2014 <b>{{FamilyName}}</b>. {{FamilyWhy}} <span class="fine">(specifically: {{FineName}})</span></div>{{/IsCorrect}}
<div class="explanation"><span class="ex-h">Why</span>{{Explanation}}</div>"""

_JUDGE_FRONT2 = """<div class="sharpe-judge" data-qid="{{QID}}" data-verdict="{{Verdict}}" data-trap="{{Trap}}">
  <div class="hdr">{{Skill}} &middot; Difficulty {{Difficulty}}</div>
  <div class="stim">{{Stimulus}}</div>
  <div class="qst">{{Question}}</div>
  <div class="one-choice"><span class="lc">{{ChoiceLetter}}</span><span class="ct">{{Choice}}</span></div>
  <div class="ask">Is this the correct answer?</div>
  <div class="judge-btns">
    <button class="jb yes" data-j="right">Right</button>
    <button class="jb no" data-j="wrong">Wrong</button>
  </div>
  <div class="trap-pick" style="display:none">
    <div class="ask2">What kind of flaw is it?</div>
    <div class="trap-opts"></div>
  </div>
  <div class="result"></div>
  <div class="hint">Lock in Right or Wrong (and the flaw), then tap Show answer to see if you were right.</div>
</div>
<script>
(function () {
  var root = document.querySelector('.sharpe-judge');
  if (!root) return;
  var qid = root.getAttribute('data-qid');
  var DATA = __FAMILYJSON__;
  var FAM = DATA.families, FINE = DATA.fine;
  var verdict = root.getAttribute('data-verdict');
  var fineId = root.getAttribute('data-trap') || '';
  var flawed = verdict === 'flawed';
  var correctFam = (FINE[fineId] || {}).family || '';
  var pick = root.querySelector('.trap-pick');
  var opts = root.querySelector('.trap-opts');
  var result = root.querySelector('.result');
  var jbs = Array.prototype.slice.call(root.querySelectorAll('.jb'));
  var KEY = 'sharpe:pick:' + qid;
  function say(cls, h) { if (result) { result.className = 'result ' + cls; result.innerHTML = h; } }

  // ANSWER SIDE (the back template appends #sharpe-judge-data): show the pick the
  // student locked in. The credited/trap reveal itself is rendered statically below,
  // so nothing is graded here \u2014 and nothing is revealed on the question side.
  if (document.getElementById('sharpe-judge-data')) {
    var mine = null;
    try { mine = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) {}
    if (mine) {
      jbs.forEach(function (x) { if (x.getAttribute('data-j') === mine.v) x.classList.add('sel'); });
      if (mine.v === 'wrong' && mine.f) {
        pick.style.display = 'block';
        Object.keys(FAM).forEach(function (fid) {
          var b = document.createElement('button');
          b.className = 'topt' + (fid === mine.f ? ' sel' : '');
          b.textContent = FAM[fid].name; opts.appendChild(b);
        });
      }
      var right = !flawed ? (mine.v === 'right') : (mine.v === 'wrong' && mine.f === correctFam);
      var famNm = mine.f ? ((FAM[mine.f] || { name: mine.f }).name) : '';
      var youSaid = mine.v === 'right' ? 'Right' : ('Wrong' + (famNm ? ' \u00b7 ' + famNm : ''));
      say(right ? 'ok' : 'bad', (right ? '\u2713' : '\u2717') + ' Your call: <b>' + youSaid + '</b>' + (right ? ' \u2014 correct.' : '.'));
    }
    return;
  }

  // QUESTION SIDE: record the pick only. No correctness shown until Show answer.
  var myVerdict = null, myFam = null, done = false;
  function commit() {
    done = true;
    try { localStorage.setItem(KEY, JSON.stringify({ v: myVerdict, f: myFam })); } catch (e) {}
    var clean, tempted = [];
    if (!flawed) clean = (myVerdict === 'right');
    else if (myVerdict === 'right') { clean = false; tempted = [fineId]; }
    else { clean = (myFam === correctFam); if (!clean) tempted = [fineId]; }
    try { if (window.pycmd) window.pycmd('sharpe:attempt:' + JSON.stringify({ qid: qid, clean: !!clean, tempted: tempted })); } catch (e) {}
    say('warn', 'Locked in \u2014 tap <b>Show answer</b> to see if you were right.');
  }
  jbs.forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (done) return;
      var j = btn.getAttribute('data-j');
      jbs.forEach(function (x) { x.classList.remove('sel'); });
      btn.classList.add('sel'); myVerdict = j; myFam = null;
      if (j === 'wrong') {
        pick.style.display = 'block'; say('', ''); opts.innerHTML = '';
        Object.keys(FAM).forEach(function (fid) {
          var b = document.createElement('button');
          b.className = 'topt'; b.textContent = FAM[fid].name;
          b.addEventListener('click', function () {
            if (done) return;
            Array.prototype.slice.call(opts.querySelectorAll('.topt')).forEach(function (x) { x.classList.remove('sel'); });
            b.classList.add('sel'); myFam = fid; commit();
          });
          opts.appendChild(b);
        });
      } else { pick.style.display = 'none'; commit(); }
    });
  });
})();
</script>"""

JUDGE_FRONT = _JUDGE_FRONT2.replace("__FAMILYJSON__", _family_js())
JUDGE_BACK = _JUDGE_BACK


def ensure_judge_model(col):
    """Create or refresh the Sharpe Judge (Mode 1) note type."""
    mm = col.models
    m = mm.by_name(MODEL_JUDGE)
    if m is None:
        m = mm.new(MODEL_JUDGE)
        for f in FIELDS_JUDGE:
            mm.add_field(m, mm.new_field(f))
        t = mm.new_template("Judge")
        t["qfmt"] = JUDGE_FRONT
        t["afmt"] = JUDGE_BACK
        mm.add_template(m, t)
        m["css"] = JUDGE_CSS
        mm.add(m)
    else:
        existing = {f["name"] for f in m["flds"]}
        for f in FIELDS_JUDGE:
            if f not in existing:
                mm.add_field(m, mm.new_field(f))
        m["css"] = JUDGE_CSS
        m["tmpls"][0]["qfmt"] = JUDGE_FRONT
        m["tmpls"][0]["afmt"] = JUDGE_BACK
        mm.update_dict(m)
    return mm.by_name(MODEL_JUDGE)


def judge_specs(card: dict) -> list[dict]:
    """Expand one question into per-choice judge specs (Mode 1 cards)."""
    traps = card.get("choiceTraps") or [None] * len(card["choices"])
    specs = []
    for i, ch in enumerate(card["choices"]):
        correct = i == card["answerIndex"]
        specs.append({
            "qid": f'{card["id"]}-{LETTERS[i]}',
            "skill": skill_name(card),
            "skill_tag": next((t for t in card.get("tags", []) if t.startswith("lsat::lr::")), ""),
            "difficulty": str(card.get("difficulty", "")),
            "stimulus": card.get("stimulus", ""),
            "question": card["question"],
            "letter": LETTERS[i],
            "choice": ch,
            "verdict": "correct" if correct else "flawed",
            "trap": "" if correct else (traps[i] or ""),
            "explanation": card["explanation"],
        })
    return specs


def populate_judge(note, spec: dict) -> None:
    note["QID"] = spec["qid"]
    note["Skill"] = spec["skill"]
    note["Difficulty"] = spec["difficulty"]
    note["Stimulus"] = spec["stimulus"]
    note["Question"] = spec["question"]
    note["ChoiceLetter"] = spec["letter"]
    note["Choice"] = spec["choice"]
    note["Verdict"] = spec["verdict"]
    note["Trap"] = spec["trap"]
    note["Explanation"] = spec["explanation"]
    correct = spec["verdict"] == "correct"
    note["IsCorrect"] = "1" if correct else ""
    if correct:
        note["FamilyName"] = note["FamilyWhy"] = note["FineName"] = ""
    else:
        fam = FINE_TO_FAMILY.get(spec["trap"], "")
        fn = TRAP_FAMILIES.get(fam, (spec["trap"], ""))
        note["FamilyName"] = fn[0]
        note["FamilyWhy"] = fn[1]
        note["FineName"] = TRAP_INFO.get(
            spec["trap"], (spec["trap"].replace("_", " ").capitalize(), "")
        )[0]


def judge_note_tags(spec: dict) -> list[str]:
    tags = ["lsat::type::practice", "lsat::mode::judge", f'id::{spec["qid"]}']
    if spec.get("skill_tag"):
        tags.append(spec["skill_tag"])
    if spec.get("trap"):
        tags.append(f'trap::{spec["trap"]}')
    return tags


def render_judge_front(spec: dict) -> str:
    h = JUDGE_FRONT
    h = h.replace("{{QID}}", spec["qid"])
    h = h.replace("{{Skill}}", spec["skill"])
    h = h.replace("{{Difficulty}}", spec["difficulty"])
    h = h.replace("{{Stimulus}}", spec["stimulus"])
    h = h.replace("{{Question}}", spec["question"])
    h = h.replace("{{ChoiceLetter}}", spec["letter"])
    h = h.replace("{{Choice}}", html.escape(spec["choice"]))
    h = h.replace("{{Verdict}}", spec["verdict"])
    h = h.replace("{{Trap}}", spec["trap"] or "")
    return h


def render_judge_back(spec: dict) -> str:
    """Preview equivalent of the static answer template."""
    front = render_judge_front(spec)
    if spec["verdict"] == "correct":
        reveal = '<div class="reveal ok">\u2713 This is the credited (correct) answer.</div>'
    else:
        fam = FINE_TO_FAMILY.get(spec["trap"], "")
        fn = TRAP_FAMILIES.get(fam, (spec["trap"], ""))
        fine = TRAP_INFO.get(spec["trap"], (spec["trap"].replace("_", " ").capitalize(), ""))[0]
        reveal = (
            f'<div class="reveal trap">\u2717 This is a trap \u2014 <b>{fn[0]}</b>. '
            f'{fn[1]} <span class="fine">(specifically: {fine})</span></div>'
        )
    data = (
        f'<div id="sharpe-judge-data" data-verdict="{spec["verdict"]}" '
        f'data-trap="{spec["trap"] or ""}" style="display:none"></div>'
    )
    expl = f'<div class="explanation"><span class="ex-h">Why</span>{spec["explanation"]}</div>'
    return f"{front}\n{data}\n{reveal}\n{expl}"
