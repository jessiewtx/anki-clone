import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInAnonymously,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import {
  getFirestore,
  doc,
  getDoc,
  setDoc,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "AIzaSyBugDnI867Temo60agzKEq6LtL20GGzlyw",
  authDomain: "speedrun-lsat-jwang.firebaseapp.com",
  projectId: "speedrun-lsat-jwang",
  storageBucket: "speedrun-lsat-jwang.firebasestorage.app",
  messagingSenderId: "946919567336",
  appId: "1:946919567336:web:1edef8ea2a0563a0bbfe5d",
};
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

const LETTERS = ["A", "B", "C", "D", "E", "F", "G"];
let USER = null;
let DECK = null; // {cards:[{id,deck,front,back}], sources}
let PROGRESS = {}; // cardId -> {dueDay, ivl, reps}
let SCORES = null;
let TAB = "study";

const $ = (id) => document.getElementById(id);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
const fmtPct = (x) => (x * 100).toFixed(0) + "%";
const todayDay = () => Math.floor(Date.now() / 86400000);

// ---------- deck loading / formatting (mirrors build_deck.py) ----------
function sourceLine(raw) {
  const s = DECK.sources[raw.source] || { name: raw.source, url: "" };
  const tail = raw.type === "practice" ? " · original practice item" : "";
  return `<i class="src">Source: ${s.name} — ${s.url}${tail}</i>`;
}
function formatCard(raw) {
  const deck = raw.type === "concept" ? "LSAT::Concepts" : "LSAT::Practice";
  let front, back;
  if (raw.type === "concept") {
    front = raw.front;
    back = `${raw.back}<br><br>${sourceLine(raw)}`;
  } else {
    const stim = raw.stimulus ? `${raw.stimulus}<br><br>` : "";
    const choices = raw.choices.map((c, i) => `${LETTERS[i]}. ${c}`).join("<br>");
    front = `${stim}<b>${raw.question}</b><br><br>${choices}`;
    back = `<b>Answer: ${LETTERS[raw.answerIndex]}.</b> ${raw.choices[raw.answerIndex]}<br><br>${raw.explanation}<br><br>${sourceLine(raw)}`;
  }
  return { id: raw.id, deck, front, back };
}
async function loadDeck() {
  if (DECK) return;
  const raw = await (await fetch("deck.json", { cache: "no-store" })).json();
  // Assign DECK.sources BEFORE mapping: formatCard() reads DECK.sources.
  DECK = { sources: raw.sources, cards: [] };
  DECK.cards = raw.cards.map(formatCard);
}

// ---------- scheduling (simple, companion) ----------
function nextIvl(prev, reps, rating) {
  if (rating === 1) return 0; // Again -> due again now
  if (!prev || !reps) return rating === 2 ? 1 : rating === 3 ? 3 : 7;
  const f = rating === 2 ? 1.2 : rating === 3 ? 2.5 : 4;
  return Math.max(1, Math.round(prev * f));
}
const ivlLabel = (d) => (d <= 0 ? "today" : d + "d");
function counts(cards) {
  const t = todayDay();
  let nw = 0,
    due = 0;
  for (const c of cards) {
    const p = PROGRESS[c.id];
    if (!p) nw++;
    else if (p.dueDay <= t) due++;
  }
  return { nw, due };
}
async function saveProgress() {
  if (!USER) return;
  await setDoc(doc(db, "users", USER.uid), { study: PROGRESS }, { merge: true });
}

// ---------- study view ----------
function renderStudyHome() {
  const v = $("view");
  v.innerHTML = "";
  v.append(el("p", "deckhdr", "Decks — tap to study (new / learning / due)"));
  const groups = [
    ["LSAT::Concepts", "Concepts", false],
    ["LSAT::Practice", "Practice", false],
  ];
  // parent row
  const allCards = DECK.cards;
  const total = counts(allCards);
  const parent = el("div", "deckrow");
  parent.append(el("span", "name", "LSAT"));
  const pc = el("span", "counts");
  pc.append(el("span", "c-new", String(total.nw)), el("span", "c-learn", "0"), el("span", "c-rev", String(total.due)));
  parent.append(pc);
  parent.onclick = () => startDeck(null, "LSAT");
  v.append(parent);
  for (const [deck, label] of groups) {
    const cards = allCards.filter((c) => c.deck === deck);
    const ct = counts(cards);
    const row = el("div", "deckrow");
    row.append(el("span", "name indent", label));
    const cc = el("span", "counts");
    cc.append(el("span", "c-new", String(ct.nw)), el("span", "c-learn", "0"), el("span", "c-rev", String(ct.due)));
    row.append(cc);
    row.onclick = () => startDeck(deck, label);
    v.append(row);
  }
}

function buildQueue(deck) {
  const t = todayDay();
  const pool = DECK.cards.filter((c) => deck === null || c.deck === deck);
  const due = pool.filter((c) => PROGRESS[c.id] && PROGRESS[c.id].dueDay <= t);
  const news = pool.filter((c) => !PROGRESS[c.id]).slice(0, 20); // new-per-day cap like Anki
  return [...due, ...news];
}

function startDeck(deck, label) {
  const queue = buildQueue(deck);
  renderReviewer(queue, 0, label, deck);
}

function renderReviewer(queue, idx, label, deck) {
  const v = $("view");
  v.innerHTML = "";
  const back = el("button", "backlink", "‹ Decks");
  back.onclick = () => renderStudyHome();
  v.append(back);

  if (idx >= queue.length) {
    const d = el("div", "rev");
    d.append(el("div", "done", `Congratulations — ${label} is finished for now. · Speedrun LSAT`));
    v.append(d);
    return;
  }
  const card = queue[idx];
  const remaining = queue.length - idx;
  const rev = el("div", "rev");
  const c2 = el("div", "counts2");
  c2.append(el("span", "c-rev", `${remaining} to review`));
  rev.append(c2);
  const body = el("div", "cardbody");
  body.innerHTML = card.front;
  rev.append(body);
  const controls = el("div", "controls");
  const show = el("button", "showbtn", "Show answer");
  show.onclick = () => {
    const div = el("div", "qdiv");
    body.append(div);
    const ans = el("div");
    ans.innerHTML = card.back;
    body.append(ans);
    controls.innerHTML = "";
    const rates = el("div", "rates");
    [
      [1, "Again", "again"],
      [2, "Hard", "hard"],
      [3, "Good", "good"],
      [4, "Easy", "easy"],
    ].forEach(([rating, lbl, cls]) => {
      const p = PROGRESS[card.id];
      const iv = nextIvl(p ? p.ivl : 0, p ? p.reps : 0, rating);
      const b = el("button", "rate " + cls);
      b.append(el("span", "ivl", ivlLabel(iv)), el("span", "lbl", lbl));
      b.onclick = async () => {
        const prev = PROGRESS[card.id] || { reps: 0, ivl: 0 };
        const iv2 = nextIvl(prev.ivl, prev.reps, rating);
        PROGRESS[card.id] = { dueDay: todayDay() + iv2, ivl: iv2, reps: prev.reps + 1 };
        const nextQueue = rating === 1 ? [...queue, card] : queue;
        saveProgress().catch(() => {});
        renderReviewer(nextQueue, idx + 1, label, deck);
      };
      rates.append(b);
    });
    controls.append(rates);
  };
  controls.append(show);
  rev.append(controls);
  v.append(rev);
}

// ---------- dashboard view ----------
function rangeBar(lo, hi, point, min, max) {
  const pct = (x) => Math.max(0, Math.min(100, ((x - min) / (max - min)) * 100));
  const wrap = el("div", "bar2");
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
  return (p[1] || "").toUpperCase() + " · " + (p[2] || "").replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
function dashCards(d) {
  const frag = document.createDocumentFragment();
  const cov = el("div", "card coverage");
  cov.append(el("h2", null, "Exam coverage"), el("p", "q", "Scored skills your deck covers."), el("div", "big", fmtPct(d.coverage.pct)), rangeBar(0, d.coverage.pct, d.coverage.pct, 0, 1), el("p", "meta", `${d.coverage.covered_skills} of ${d.coverage.total_skills} skills`));
  const sc = (title, q, s) => {
    const c = el("div", "card");
    c.append(el("h2", null, title), el("p", "q", q));
    const n = s.n_reviews != null ? s.n_reviews : s.n_attempts;
    if (!n) c.append(el("div", "nodata", "Not enough data"));
    else { c.append(el("div", "big", fmtPct(s.point)), rangeBar(s.lo, s.hi, s.point, 0, 1), el("p", "range", `likely ${fmtPct(s.lo)}–${fmtPct(s.hi)}`)); }
    c.append(el("p", "meta", `confidence: ${s.confidence} · n=${n}`), el("p", "method", s.method));
    return c;
  };
  const r = d.readiness;
  const rc = el("div", "card readiness");
  rc.append(el("h2", null, "Readiness"), el("p", "q", "Projected LSAT (120–180), honest about uncertainty."));
  if (r.gave_up) {
    rc.classList.add("abstain");
    rc.append(el("div", "abstain-badge", "Not enough data — no score shown"));
    const ul = el("ul", "missing");
    (r.missing || []).forEach((m) => ul.append(el("li", null, m)));
    rc.append(ul, el("p", "rule", "Give-up rule: " + r.give_up_rule));
  } else {
    rc.append(el("div", "big", String(r.point)), rangeBar(r.lo, r.hi, r.point, 120, 180), el("p", "range", `likely ${r.lo}–${r.hi}`), el("p", "meta", `confidence: ${r.confidence}`));
    (r.reasons || []).forEach((x) => rc.append(el("p", "reason", "• " + x)));
  }
  const nx = el("div", "card next");
  nx.append(el("h2", null, "What to study next"), el("p", "q", "weakness × exam weight (Rust skill-weakness queue)."));
  const ol = el("ol");
  (d.next_to_study || []).forEach((s) => { const li = el("li"); li.append(el("span", "skill", prettySkill(s.skill)), el("span", "pri", `priority ${s.priority}`)); ol.append(li); });
  nx.append(ol);
  frag.append(cov, sc("Memory", "Recall a fact right now?", d.memory), sc("Performance", "Answer a new exam-style question?", d.performance), rc, nx);
  return frag;
}
function renderDashboard() {
  const v = $("view");
  v.innerHTML = "";
  if (SCORES) {
    v.append(el("p", "updated", `Updated ${SCORES.updated_at} · exam ${SCORES.exam}`));
    const g = el("div", "grid");
    g.append(dashCards(SCORES));
    v.append(g);
  } else {
    const c = el("div", "card readiness abstain");
    c.append(el("h2", null, "No scores synced yet"), el("p", "q", "No engine-computed scores for this account yet — and we will not invent a number."), el("div", "abstain-badge", "Readiness: no score (give-up rule)"));
    const btn = el("button", "btn", "Load demo scores (from the seed deck)");
    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = "Loading…";
      SCORES = await (await fetch("scores.json", { cache: "no-store" })).json();
      await setDoc(doc(db, "users", USER.uid), { scores: SCORES }, { merge: true });
      renderDashboard();
    };
    c.append(btn);
    v.append(c);
  }
}

// ---------- shell ----------
function renderTab() {
  $("tab-study").classList.toggle("active", TAB === "study");
  $("tab-dash").classList.toggle("active", TAB === "dash");
  if (!USER) {
    $("view").innerHTML = "<p class='loading'>Sign in (or continue as guest) to study and see your scores.</p>";
    return;
  }
  if (TAB === "study") renderStudyHome();
  else renderDashboard();
}
$("tab-study").onclick = () => { TAB = "study"; renderTab(); };
$("tab-dash").onclick = () => { TAB = "dash"; renderTab(); };

function authBarSignedIn(user) {
  const bar = $("authbar");
  bar.innerHTML = "";
  bar.append(el("span", "who", user.isAnonymous ? "guest" : user.email || "signed in"));
  const out = el("button", "linkbtn", "Sign out");
  out.onclick = () => signOut(auth);
  bar.append(out);
}
function authBarSignedOut() {
  const bar = $("authbar");
  bar.innerHTML = "";
  const form = el("div", "signin");
  const email = el("input"); email.type = "email"; email.placeholder = "email";
  const pass = el("input"); pass.type = "password"; pass.placeholder = "password";
  const msg = el("span", "msg");
  const run = async (fn) => { msg.textContent = ""; try { await fn(auth, email.value.trim(), pass.value); } catch (e) { msg.textContent = (e.code || e.message || "error").replace("auth/", ""); } };
  const inBtn = el("button", "btn", "Sign in"); inBtn.onclick = () => run(signInWithEmailAndPassword);
  const upBtn = el("button", "linkbtn", "Sign up"); upBtn.onclick = () => run(createUserWithEmailAndPassword);
  const g = el("button", "btn", "Google"); g.onclick = async () => { msg.textContent = ""; try { await signInWithPopup(auth, new GoogleAuthProvider()); } catch (e) { msg.textContent = (e.code || e.message || "error").replace("auth/", ""); } };
  const guest = el("button", "linkbtn", "Guest"); guest.onclick = async () => { try { await signInAnonymously(auth); } catch (e) { msg.textContent = e.code || e.message; } };
  form.append(email, pass, inBtn, upBtn, g, guest, msg);
  bar.append(form);
}

onAuthStateChanged(auth, async (user) => {
  USER = user;
  if (!user) { authBarSignedOut(); renderTab(); return; }
  authBarSignedIn(user);
  try {
    await loadDeck();
    const snap = await getDoc(doc(db, "users", user.uid));
    const data = snap.exists() ? snap.data() : {};
    PROGRESS = data.study || {};
    SCORES = data.scores || null;
  } catch (e) {
    $("view").innerHTML = "<p class='loading'>Error: " + (e.message || e) + "</p>";
    return;
  }
  renderTab();
});
