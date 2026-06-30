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

const fmtPct = (x) => (x * 100).toFixed(0) + "%";
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
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
  return (
    (p[1] || "").toUpperCase() +
    " · " +
    (p[2] || "").replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase())
  );
}

function coverageCard(cov) {
  const c = el("div", "card coverage");
  c.append(el("h2", null, "Exam coverage"));
  c.append(el("p", "q", "Share of the exam's scored skills your deck covers."));
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

function renderScores(d) {
  const appEl = document.getElementById("app");
  document.getElementById("updated").textContent =
    `Updated ${d.updated_at} · exam ${d.exam}`;
  appEl.innerHTML = "";
  appEl.append(
    coverageCard(d.coverage),
    scoreCard("Memory", "Can you recall a fact right now?", d.memory),
    scoreCard("Performance", "Can you answer a new, exam-style question?", d.performance),
    readinessCard(d.readiness),
    nextCard(d.next_to_study)
  );
}

function renderNoData(user) {
  const appEl = document.getElementById("app");
  document.getElementById("updated").textContent = "";
  appEl.innerHTML = "";
  const c = el("div", "card readiness abstain");
  c.append(el("h2", null, "No study data synced yet"));
  c.append(
    el(
      "p",
      "q",
      "This account has no reviews synced, so there is nothing to score yet — and we will not invent a number."
    )
  );
  c.append(el("div", "abstain-badge", "Readiness: no score (give-up rule)"));
  const btn = el("button", "btn", "Load demo scores (from the seed deck)");
  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = "Loading…";
    const res = await fetch("scores.json", { cache: "no-store" });
    const scores = await res.json();
    await setDoc(doc(db, "users", user.uid), scores);
    renderScores(scores);
  };
  c.append(btn);
  appEl.append(c);
}

async function loadForUser(user) {
  const snap = await getDoc(doc(db, "users", user.uid));
  if (snap.exists()) {
    renderScores(snap.data());
  } else {
    renderNoData(user);
  }
}

function renderAuthBarSignedIn(user) {
  const bar = document.getElementById("authbar");
  bar.innerHTML = "";
  const who = user.isAnonymous ? "guest" : user.email || user.uid;
  bar.append(el("span", "who", `Signed in as ${who}`));
  const out = el("button", "linkbtn", "Sign out");
  out.onclick = () => signOut(auth);
  bar.append(out);
}

function renderAuthBarSignedOut() {
  const bar = document.getElementById("authbar");
  bar.innerHTML = "";
  const form = el("div", "signin");
  const email = el("input");
  email.type = "email";
  email.placeholder = "email";
  const pass = el("input");
  pass.type = "password";
  pass.placeholder = "password";
  const msg = el("span", "msg");
  const run = async (fn) => {
    msg.textContent = "";
    try {
      await fn(auth, email.value.trim(), pass.value);
    } catch (e) {
      msg.textContent = (e.code || e.message || "error").replace("auth/", "");
    }
  };
  const inBtn = el("button", "btn", "Sign in");
  inBtn.onclick = () => run(signInWithEmailAndPassword);
  const upBtn = el("button", "linkbtn", "Sign up");
  upBtn.onclick = () => run(createUserWithEmailAndPassword);
  const google = el("button", "btn", "Sign in with Google");
  google.onclick = async () => {
    msg.textContent = "";
    try {
      await signInWithPopup(auth, new GoogleAuthProvider());
    } catch (e) {
      msg.textContent = (e.code || e.message || "error").replace("auth/", "");
    }
  };
  const guest = el("button", "linkbtn", "Continue as guest");
  guest.onclick = async () => {
    try {
      await signInAnonymously(auth);
    } catch (e) {
      msg.textContent = e.code || e.message;
    }
  };
  form.append(email, pass, inBtn, upBtn, google, guest, msg);
  bar.append(form);

  const appEl = document.getElementById("app");
  document.getElementById("updated").textContent = "";
  appEl.innerHTML =
    "<p class='loading'>Sign in (or continue as guest) to see your readiness dashboard.</p>";
}

onAuthStateChanged(auth, (user) => {
  if (user) {
    renderAuthBarSignedIn(user);
    loadForUser(user).catch((e) => {
      document.getElementById("app").innerHTML =
        "<p class='loading'>Error loading scores: " + (e.message || e) + "</p>";
    });
  } else {
    renderAuthBarSignedOut();
  }
});
