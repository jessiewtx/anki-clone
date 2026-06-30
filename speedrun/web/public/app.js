"use strict";

const fmtPct = (x) => (x * 100).toFixed(0) + "%";

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

// Range bar across [min,max]: a shaded band from lo..hi with a marker at point.
function rangeBar(lo, hi, point, min, max) {
  const pct = (v) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100));
  const wrap = el("div", "bar");
  const band = el("div", "band");
  band.style.left = pct(lo) + "%";
  band.style.width = pct(hi) - pct(lo) + "%";
  const mark = el("div", "mark");
  mark.style.left = pct(point) + "%";
  wrap.append(band, mark);
  return wrap;
}

function prettySkill(tag) {
  const p = tag.split("::");
  const sec = (p[1] || "").toUpperCase();
  const name = (p[2] || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
  return sec + " · " + name;
}

function coverageCard(cov) {
  const c = el("div", "card coverage");
  c.append(el("h2", null, "Exam coverage"));
  c.append(el("p", "q", "Share of the exam's scored skills your deck actually covers."));
  c.append(el("div", "big", fmtPct(cov.pct)));
  c.append(rangeBar(0, cov.pct, cov.pct, 0, 1));
  c.append(el("p", "meta", `${cov.covered_skills} of ${cov.total_skills} scored skills covered`));
  return c;
}

function scoreCard(title, q, s) {
  const c = el("div", "card");
  c.append(el("h2", null, title));
  c.append(el("p", "q", q));
  const n = s.n_reviews != null ? s.n_reviews : s.n_attempts;
  if (!n) {
    c.append(el("div", "nodata", "Not enough data"));
  } else {
    c.append(el("div", "big", fmtPct(s.point)));
    c.append(rangeBar(s.lo, s.hi, s.point, 0, 1));
    c.append(el("p", "range", `likely ${fmtPct(s.lo)}–${fmtPct(s.hi)}`));
  }
  c.append(el("p", "meta", `confidence: ${s.confidence} · n=${n}`));
  c.append(el("p", "method", s.method));
  return c;
}

function readinessCard(r) {
  const c = el("div", "card readiness");
  c.append(el("h2", null, "Readiness"));
  c.append(el("p", "q", "Projected LSAT score (120–180), with honesty about uncertainty."));
  if (r.gave_up) {
    c.classList.add("abstain");
    c.append(el("div", "abstain-badge", "Not enough data — no score shown"));
    const ul = el("ul", "missing");
    (r.missing || []).forEach((m) => ul.append(el("li", null, m)));
    c.append(ul);
    c.append(el("p", "rule", "Give-up rule: " + r.give_up_rule));
  } else {
    c.append(el("div", "big", String(r.point)));
    c.append(rangeBar(r.lo, r.hi, r.point, 120, 180));
    c.append(el("p", "range", `likely ${r.lo}–${r.hi} (scale ${r.scale})`));
    c.append(el("p", "meta", `confidence: ${r.confidence}`));
    (r.reasons || []).forEach((x) => c.append(el("p", "reason", "• " + x)));
  }
  return c;
}

function nextCard(list) {
  const c = el("div", "card next");
  c.append(el("h2", null, "What to study next"));
  c.append(el("p", "q", "Highest-value skills = weakness × exam weight (from the Rust skill-weakness queue)."));
  const ol = el("ol");
  (list || []).forEach((s) => {
    const li = el("li");
    li.append(el("span", "skill", prettySkill(s.skill)));
    li.append(el("span", "pri", `priority ${s.priority}`));
    ol.append(li);
  });
  c.append(ol);
  return c;
}

async function main() {
  const app = document.getElementById("app");
  let d;
  try {
    const res = await fetch("scores.json", { cache: "no-store" });
    d = await res.json();
  } catch (e) {
    app.innerHTML = "<p class='loading'>Could not load scores.</p>";
    return;
  }
  document.getElementById("updated").textContent =
    `Updated ${d.updated_at} · exam ${d.exam}`;
  app.innerHTML = "";
  app.append(
    coverageCard(d.coverage),
    scoreCard("Memory", "Can you recall a fact right now?", d.memory),
    scoreCard("Performance", "Can you answer a new, exam-style question?", d.performance),
    readinessCard(d.readiness),
    nextCard(d.next_to_study)
  );
}

main();
