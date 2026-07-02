#!/usr/bin/env python3
"""Render a standalone, interactive preview of the Sharpe LR elimination card.

Writes out/gym_preview.html using the *same* template as the real Anki note
type (from sharpe_lr.py), so what you see here is what the app renders. Open it
in any browser: tap choices to rule them out, then "Show Answer".

    out/pyenv/bin/python speedrun/scripts/preview_gym.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import sharpe_lr  # noqa: E402

SEED = os.path.join(ROOT, "speedrun", "decks", "lsat_seed.json")
OUT = os.path.join(ROOT, "out", "gym_preview.html")


def pick_specs(data: dict) -> list[dict]:
    """A mix of Mode-1 judge cards: a couple of traps + the credited answer, from
    the first two elimination questions."""
    elim = [c for c in data["cards"] if c.get("choiceTraps") and c.get("type") == "practice"]
    specs = []
    for card in elim[:2]:
        ss = sharpe_lr.judge_specs(card)
        flawed = [s for s in ss if s["verdict"] == "flawed"]
        correct = [s for s in ss if s["verdict"] == "correct"]
        specs += flawed[:2] + correct[:1]
    return specs


def main() -> int:
    data = json.load(open(SEED, encoding="utf-8"))
    specs = pick_specs(data)
    if not specs:
        print("no elimination cards found (need choiceTraps)")
        return 1

    fronts = [sharpe_lr.render_judge_front(s) for s in specs]
    backs = [sharpe_lr.render_judge_back(s) for s in specs]

    template = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sharpe - elimination gym preview</title>
<style>
@@CSS@@
body { background: #f4f4f7; margin: 0; padding: 28px 16px 60px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width: 700px; margin: 0 auto; }
.brandbar { display: flex; align-items: center; gap: 10px; margin: 0 auto 18px; max-width: 700px; }
.brandbar b { color: #1a1a2e; font-size: 18px; }
.brandbar .pill { margin-left: auto; font-size: 12px; color: #8a8a93; }
.card { background: #fff; padding: 24px; border-radius: 16px; box-shadow: 0 2px 16px rgba(0,0,0,.06); }
.bar { display: flex; gap: 10px; max-width: 700px; margin: 16px auto 0; }
button { padding: 10px 18px; border: 0; border-radius: 10px; font-weight: 700; font-size: 15px; cursor: pointer; }
#show { background: #F47A38; color: #fff; }
#again, #next { background: #ececf2; color: #1a1a2e; }
button:disabled { opacity: .5; cursor: default; }
</style></head><body>
<div class="brandbar"><b>Sharpe &mdash; Trap Spotter</b><span class="pill">Mode 1 &middot; @@N@@ cards</span></div>
<div class="wrap"><div class="card" id="app"></div></div>
<div class="bar">
  <button id="show">Show Answer</button>
  <button id="again">Try again</button>
  <button id="next">Next question &rarr;</button>
</div>
<script>
var FRONTS = @@FRONTS@@;
var BACKS = @@BACKS@@;
var idx = 0;
function runScripts(container) {
  container.querySelectorAll('script').forEach(function (old) {
    var s = document.createElement('script');
    if (old.src) s.src = old.src; else s.textContent = old.textContent;
    old.parentNode.replaceChild(s, old);
  });
}
function render(h) { var a = document.getElementById('app'); a.innerHTML = h; runScripts(a); }
function showFront() { render(FRONTS[idx]); document.getElementById('show').disabled = false; document.getElementById('show').textContent = 'Show Answer'; }
showFront();
document.getElementById('show').onclick = function () { render(BACKS[idx]); this.disabled = true; this.textContent = 'Answer shown'; };
document.getElementById('again').onclick = function () { showFront(); };
document.getElementById('next').onclick = function () { idx = (idx + 1) % FRONTS.length; showFront(); };
</script>
</body></html>"""
    # Escape </ so a card's inline </script> can't close the outer <script> that
    # holds these arrays (JS reads <\/ as </). Only needed for this preview harness.
    fronts_json = json.dumps(fronts).replace("</", "<\\/")
    backs_json = json.dumps(backs).replace("</", "<\\/")
    page = (
        template.replace("@@CSS@@", sharpe_lr.JUDGE_CSS)
        .replace("@@N@@", str(len(specs)))
        .replace("@@FRONTS@@", fronts_json)
        .replace("@@BACKS@@", backs_json)
    )

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("wrote", OUT, "with", len(specs), "cards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
