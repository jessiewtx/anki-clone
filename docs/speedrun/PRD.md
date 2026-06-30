# Speedrun LSAT — PRD, Data Schema & Architecture

**Product:** An Anki fork (desktop) + Android companion that share one Rust engine and turn LSAT study into three honest, separately-reported scores.
**Exam:** LSAT (scored 120–180; 2 Logical Reasoning + 1 Reading Comprehension scored sections; writing + experimental unscored).
**Thesis (from brainlift):** Spaced repetition is "a great solution to the wrong problem" for the LSAT (SPOV 1). The LSAT tests *applied reasoning*, not recall — so we measure the gap between memory and performance, and use AI to generate *novel* reasoning problems (SPOV 2).

---

## 1. Decisions (defaults — tell me to flip any)

| Decision | Default | Why this default |
|---|---|---|
| Exam | **LSAT** | Locked (your brainlift) |
| Mobile target | **AnkiDroid (Android emulator)** | Open-source AGPL, already wraps the shared Rust backend → easiest "one engine + sync." (iOS-via-FFI is valid but more signing friction.) |
| Rust engine change | **Skill-weakness priority queue** | Sorts due cards by `skill weight × student weakness`; new protobuf message called from Python. Directly implements SPOV 2 ("rethink scheduling to surface weak reasoning skills"). |
| Study feature to ablate | **Interleaving** (mix LR skill types in a session) | Cited in your brainlift (Bjork, desirable difficulties). Hypothesis: raises accuracy on new mixed-skill questions at equal study time. |
| Sync / storage | **Anki sync (cards+reviews)** + **Firestore (LSAT score layer)** | Anki's sync already handles no-loss / no-double-count for reviews; Firestore holds skills, questions, attempts, scores, evals. |

---

## 2. Scope (MVP)

**In scope**
- LSAT on its real 120–180 scale.
- Desktop Anki fork + Android companion sharing the **same Rust engine**, two-way sync, offline-then-reconcile.
- LSAT **skill taxonomy** + **coverage map** (% of official outline the deck covers).
- **Rust change:** skill-weakness priority queue (3 Rust tests + 1 Python-callable test, undo-safe).
- **Three scores**, each with point estimate + range + coverage % + confidence + "last updated" + reasons + give-up rule:
  - Memory (FSRS, calibrated), Performance (BKT/IRT on held-out questions), Readiness (mapped to 120–180).
- **AI:** generate LR-style questions from a real source; every output traces to a named source; checked against a 50-item gold set; beats a keyword/vector baseline; **app still scores with AI off**.
- **Evals (re-runnable, held-out):** memory calibration (Brier/log-loss), performance accuracy, paraphrase test, leakage check, AI card check, one-command benchmark.
- Interleaving feature + **3-build ablation** (full / feature-off / plain Anki).

**Out of scope (MVP)**
- LSAT **writing** section (your brainlift) and **logic games** (removed Aug 2024).
- **iOS** (if Android is chosen), real-student score validation (Step 4 bonus), accounts/social, monetization.
- AI generation of full **RC passages** — RC is in the taxonomy/coverage/performance items, but MVP AI-generation targets **LR**; RC questions are curated.

---

## 3. Personas

**Primary — "Maya," self-studying retaker.** 22, recent grad, aiming ~168, can't afford a $4k course. Studies at a desk at home and on her phone between things. Wants the honest truth: *am I actually ready, and what do I drill next?*

**Secondary — cold-start beginner.** Just started; deck covers little of the exam. Needs the app to **abstain** from a readiness score and show coverage gaps.

**Not focused on:** students in full instructor-led courses (Princeton Review), casual users who only want flashcards, anyone seeking logic-games practice, non-LSAT exams.

---

## 4. User stories (essentials)

1. As a student, I review LSAT cards on **desktop or phone** and my progress **syncs both ways** without losing or double-counting reviews.
2. As a student, I see **three separate scores** (memory, performance, readiness), each with a **range**, not one blended number.
3. As a student, when I lack data the app **refuses to show a readiness score** and tells me why (coverage / # attempts).
4. As a student, I see **which skills I'm weakest at** and the app surfaces those cards **first** (Rust queue).
5. As a student, I get **AI-generated novel LR questions** for a skill, and can see the **source** each came from.
6. As a student studying offline, my reviews **queue locally** and sync cleanly when I reconnect.
7. As a student, I see **% of the LSAT my deck covers**, so I know what's missing.
8. As the evaluator (me), I can **re-run all evals with one command** and get the same numbers on held-out data.

---

## 5. Domain model (LSAT)

**Sections (scored):** Logical Reasoning (×2) and Reading Comprehension (×1) → LR ≈ ⅔ of scored items, RC ≈ ⅓. Weights are configurable and derived from released official tests.

**Skills (the unit BKT tracks, the queue weights, and coverage measures):**
- **LR:** Necessary Assumption, Sufficient Assumption, Strengthen, Weaken, Flaw, Inference / Must Be True, Main Conclusion, Method of Reasoning, Parallel Reasoning, Principle, Paradox/Resolve, Point at Issue, Role in Argument, Evaluate.
- **RC:** Main Idea, Primary Purpose, Detail/Lookup, Inference, Author's Attitude/Tone, Function of a detail, Passage Structure, Comparative passages.

Each skill has: `examWeight` (frequency on the real exam), and per-student `mastery` (BKT).

**Give-up rule (stated):** *No readiness score until the student has ≥ 200 graded performance attempts AND ≥ 50% topic coverage AND a computed calibration.* Below that, show coverage + "not enough data," never a number.

**Honesty fields (every score carries):** point estimate, likely range, coverage %, confidence indicator, last-updated time, top reasons, and the give-up rule.

---

## 6. The three scores

| Score | Question it answers | Inputs | Output |
|---|---|---|---|
| **Memory** | Can they recall this fact now? | FSRS state from review history | Recall probability + range; calibrated (Brier/log-loss) |
| **Performance** | Can they answer a *new* exam-style question for this skill? | BKT mastery per skill + question difficulty (IRT) + timing + coverage | P(correct) on held-out questions + range |
| **Readiness** | What LSAT score today, how sure? | Performance across skills × exam weights × coverage | Projected **120–180** + range + confidence + give-up |

---

## 7. Data: what's stored, where, and how it flows

### Source of truth
| Data | Owner | Store | Synced by |
|---|---|---|---|
| Decks, notes, cards, review logs, FSRS memory state | **Anki Rust engine** | Local SQLite (`collection.anki2`) | **Anki sync server** |
| Skill taxonomy + exam weights | App | Firestore (global) | Firestore |
| Per-student skill mastery (BKT), performance attempts, score snapshots, generated/gold questions, eval results, coverage | App | **Firestore** (per user) | Firestore |
| Unsynced offline attempts | App | Local cache / Firestore offline persistence | Firestore on reconnect |

### Firestore collections (fields)
- `skills/{skillId}` — `name, section (LR|RC), examWeight, description` *(global taxonomy + coverage reference)*
- `users/{uid}` — `displayName, exam:"LSAT", settings, createdAt`
- `users/{uid}/skillState/{skillId}` — `bkt {pL0,pT,pS,pG}, masteryProb, attemptsCount, lastUpdated`
- `questions/{questionId}` — `skillId, stem, choices[], answerIndex, rationale, difficulty (IRT b), origin (gold|generated|official), source {name, locator}, status (approved|blocked), checks {factual, teaching, duplicate}, createdAt`
- `users/{uid}/attempts/{attemptId}` — `questionId, skillId, correct, chosenIndex, responseMs, ts, deviceId, sessionId` *(immutable, UUID-keyed)*
- `users/{uid}/scoreSnapshots/{ts}` — `memory{p,lo,hi}, performance{p,lo,hi}, readiness{point,lo,hi}, coveragePct, confidence, reasons[], gaveUp, giveUpReason, updatedAt`
- `evals/{evalId}` — `type (memory_calibration|performance|ai_cardcheck|baseline), metrics{...}, datasetHash, gitCommit, createdAt` *(re-runnable proof)*

### Example documents
```json
// questions/lr_necassum_042
{
  "skillId": "lr_necessary_assumption",
  "stem": "The columnist concludes that ... Which one of the following is an assumption required by the argument?",
  "choices": ["...","...","...","...","..."],
  "answerIndex": 2,
  "rationale": "Negating (C) breaks the link between premise and conclusion.",
  "difficulty": 0.7,
  "origin": "generated",
  "source": { "name": "Bjork & Bjork 2011, p.58 (logic of necessity)", "locator": "para 3" },
  "status": "approved",
  "checks": { "factual": true, "teaching": true, "duplicate": false },
  "createdAt": 1751299200
}
```
```json
// users/maya/attempts/8f2c-...-a91   (UUID = deviceId + local sequence)
{ "questionId": "lr_necassum_0042", "skillId": "lr_necessary_assumption",
  "correct": false, "chosenIndex": 1, "responseMs": 41250,
  "ts": 1751299500, "deviceId": "pixel7-emu", "sessionId": "s_2026_06_30_a" }
```

### Sync & conflict rule (the part the rubric grades hard)
- **Reviews/cards:** Anki's own sync merges the collection. Rule we document: card scheduling state resolves by **latest modification time**, and **both review-log rows are preserved** (counts never lost).
- **Performance attempts:** each attempt is an **immutable document keyed by a client-generated UUID**, so two devices reviewing offline create **distinct docs → union on sync (no winner needed, no double-count)**. Re-uploading the same attempt is **idempotent** (same id overwrites itself). This is effectively conflict-free.

---

## 8. Architecture & diagrams

### 8.1 System / hardware architecture
```mermaid
flowchart TB
  subgraph Desktop["Desktop app — macOS / Windows / Linux"]
    DUI["Python + Qt UI<br/>LSAT dashboard"]
    DR["Anki Rust engine<br/>+ skill-weakness queue"]
    DDB[("Local SQLite<br/>collection.anki2")]
    DUI --> DR --> DDB
  end
  subgraph Phone["Android phone / emulator"]
    MUI["AnkiDroid UI<br/>LSAT dashboard"]
    MR["Same Anki Rust engine<br/>via JNI"]
    MDB[("Local SQLite<br/>collection.anki2")]
    MUI --> MR --> MDB
  end
  SYNC["Anki Sync Server<br/>cards + reviews"]
  FS[("Firestore<br/>skills · questions · attempts · scores · evals")]
  AI["LLM provider<br/>(optional — AI-off safe)"]

  DR <-->|sync| SYNC
  MR <-->|sync| SYNC
  DUI <-->|read/write| FS
  MUI <-->|read/write| FS
  DUI -. AI on .-> AI
  AI -. generated questions + source .-> FS
```

### 8.2 Offline review → sync (the sync test, 7b)
```mermaid
sequenceDiagram
  participant P as Phone (offline)
  participant D as Desktop (offline)
  participant S as Anki Sync Server
  participant F as Firestore
  P->>P: review 10 cards + log attempts (UUID-keyed)
  D->>D: review 10 different cards + attempts
  Note over P,D: reconnect
  P->>S: push reviews
  D->>S: push reviews
  S-->>P: merged collection (20 reviews, none lost)
  S-->>D: merged collection
  P->>F: upload attempts (idempotent by id)
  D->>F: upload attempts (idempotent by id)
  F-->>P: union of attempts (no double-count)
  F-->>D: union of attempts
```

### 8.3 Firestore data model
```mermaid
erDiagram
  USERS ||--o{ SKILLSTATE : has
  USERS ||--o{ ATTEMPTS : logs
  USERS ||--o{ SCORESNAPSHOTS : has
  SKILLS ||--o{ SKILLSTATE : parameterizes
  SKILLS ||--o{ QUESTIONS : tags
  QUESTIONS ||--o{ ATTEMPTS : answered_in

  USERS { string uid string exam string settings }
  SKILLS { string skillId string section float examWeight }
  SKILLSTATE { float masteryProb int attemptsCount json bkt }
  QUESTIONS { string skillId string origin string source string status float difficulty }
  ATTEMPTS { string questionId bool correct int responseMs string deviceId }
  SCORESNAPSHOTS { json memory json performance json readiness float coveragePct bool gaveUp }
```

---

## 9. Open questions to resolve before build
- Confirm the 5 defaults in §1 (mobile target, Rust change, study feature, sync split).
- Confirm Firestore vs. all-Anki-sync for the score layer.
- Source of the **deck content** + the **gold set** (which released/official-style LSAT material).
