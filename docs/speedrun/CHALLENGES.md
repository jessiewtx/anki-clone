# Sharpe — Concrete Challenges Tracker

Living checklist mapping every graded requirement to an honest status and the
evidence path. Updated as we build. **We do not claim a number we cannot back up.**

Legend: ✅ done · 🟡 partial · ⬜ not started · 🤖 needs the AI generator (later)

---

## 7a. The Rust change  —  🟡 (desktop done; phone pending)

Chosen: **Points-at-stake queue** + topic-aware reorder, implemented in the shared
Rust engine (not the Python UI).

| Requirement | Status | Evidence / notes |
|---|---|---|
| Sort due/new cards by `weakness × exam_weight` | ✅ | `rslib/src/scheduler/skill_priority.rs` (`build_queue`) |
| New protobuf message, called from Python | ✅ | `proto/anki/scheduler.proto` → `GetSkillWeaknessQueue`, `ReorderDeckBySkillWeakness` |
| "Not-Anki" behavior (retire solved instance, discount <8s guesses) | ✅ | `skill_priority.rs` (`is_retired`, `MIN_PROBLEM_MILLIS`) |
| ≥3 Rust unit tests | ✅ | 6 unit tests in `skill_priority.rs` |
| ≥1 test calling it from Python | ✅ | `speedrun/tests/test_skill_weakness_queue.py`, `test_reorder_by_skill_weakness.py` |
| Undo works + no corruption | ✅ | reorder uses undo-safe `sort_cards`; `test_reorder_by_skill_weakness.py` asserts `undo()` restores order |
| One-page "why Rust not Python" | ✅ | `docs/speedrun/rust-change.md` |
| Upstream files touched + merge difficulty | ✅ | table in `rust-change.md` |
| **Works on the phone build (AnkiDroid, shared engine)** | ⬜ | **HARD-LIMIT item (70% cap). Must build rslib into AnkiDroid and call the new RPC.** |

## 7b. The sync test  —  ⬜
- [ ] 10 offline reviews on phone + 10 on desktop → reconnect → all 20 land, none lost/double-counted.
- [ ] Same card reviewed on both offline → sync → conflict rule picks a clear winner.
- [ ] Write down the conflict rule (Anki: per-review log is merged by id; on divergent collections one side does a full sync — document exactly which wins and why).

## 7c. The coverage map  —  🟡
- [x] Skill/exam weights + coverage% + abstain (give-up) rule exist in the score dialog (`qt/aqt/speedrun_scores.py`).
- [ ] List **every** LSAT LR question-type on the official outline; mark covered vs not.
- [ ] Show percent covered on the dashboard; **abstain from a score** when below the line.

## 7d. The paraphrase test  —  ⬜ (no AI needed)
- [ ] Take 30 cards; write 2 exam-style reworded questions each.
- [ ] Compare card recall vs reworded-question accuracy; **report the gap** (if ~equal, performance model is just copying memory).

## 7e. The leakage check  —  🟡
- [x] Near-duplicate detector across the bank (`speedrun/scripts/check_bank.py`).
- [ ] Dedicated script: scan **training data** for any **held-out test item** or near-copy; show result is clean.

## 7f. The AI card check  —  🤖 (later, needs generator)
- Scaffolding exists: `speedrun/ai/{generator,baseline,cardcheck,run_ai_eval}.py`.
- [ ] Gold set: 50 Q&A with known-correct answers.
- [ ] Generate 50 cards from one real source; run the checker.
- [ ] Report counts: correct+useful / wrong / correct-but-bad-teaching. Set the pass cutoff **before** looking; block failures.

## 7g. The crash & offline tests  —  ⬜
- [ ] Kill each app mid-review 20× → zero corrupted collections (desktop + phone).
- [ ] Pull network → AI features off cleanly, both apps keep working and still give a score.

## 7h. The one-command benchmark  —  ⬜
- [ ] `make bench` loads a shared **50,000-card** deck and prints p50 / p95 / worst for each action in §10.

---

## 9. Score model (grade the bridge, not a made-up number)
- [ ] **Step 1 (required):** memory model calibrated — when it says 80%, recall ≈ 80% on **held-back** reviews (reliability curve + Brier).
- [ ] **Step 2 (required):** predict held-back exam-style correctness from topic mastery, difficulty, timing, coverage.
- [x] **Step 3 (required):** turn performance into a score with a stated method **and a range** — `speedrun_scores.py` (Wilson interval + abstain). *Needs to be grounded in Step 2 once built.*
- [ ] **Step 4 (bonus):** validate against real students (skip — no data; we say so honestly).

## 10. Speed & reliability targets (report p50 / p95 / worst)
| Action | Target (p95) | Status |
|---|---|---|
| Button press acknowledged | < 50 ms (desktop + phone) | ⬜ |
| Next card after grading | < 100 ms | ⬜ |
| Dashboard first load | < 1 s | ⬜ |
| Dashboard refresh | < 500 ms, no freeze | ⬜ |
| Sync of a normal session | < 5 s | ⬜ |
| Memory on 50k cards | under a stated limit (desktop + mid phone) | ⬜ |
| Cold start | < 5 s desktop / < 4 s phone | ⬜ |
| No freeze > 100 ms | — | ⬜ |
| Zero corrupted collections (crash test) | — | ⬜ (see 7g) |

---

## Hard limits (do-or-die)
| Limit | Cap if failed | Our status |
|---|---|---|
| No real Rust change | 50% | ✅ real engine change shipped (7a) — keep it genuinely in Rust |
| No phone companion sharing engine + sync | 70% | ⬜ **top eventual priority** (7a-phone + 7b) |
| No re-runnable test setup | 60% | 🟡 tests exist; need one command to run them all + fixtures |
| No held-out testing | 60% | ⬜ calibration + paraphrase + prediction (9, 7d) |
| Made-up / misleading readiness numbers | **auto fail** | ✅ abstain + ranges + reasons (`speedrun_scores.py`) — hold this line |
| App doesn't run on a clean device | 50% | 🟡 desktop `.dmg` runs (ad-hoc); verify phone on clean emulator |
| Leaked test data | score = 0 | 🟡 near-dup check; need train-vs-test leakage script (7e) |
| AI claims with no traceable source | AI = 0 | ✅ build-time gen cites sources; keep traceability |

## Adversarial cases we must survive (from §10)
memorizes wording but fails reworded (7d) · huge deck skips high-weight topic (7c abstain) ·
two cards state opposite facts · prompt-injection in a source file (7f checker) ·
taps Good without reading (response-time guard ✅) · topic with almost no history (abstain) ·
accurate but too slow (timing in Step 2) · AI cards correct-but-useless (7f) ·
score jumps from leaked test data (7e) · AI offline / rate-limited / broken output (graceful off) ·
same card on two devices offline then synced (7b conflict rule) · phone offline mid-sync / wrong clock ·
crash mid-review recovers (7g) · corrupt deck / 50k deck / broken images.

---

### Suggested order (non-AI first, since AI isn't built yet)
1. **Phone build with the Rust change + sync test** (7a-phone, 7b) — lifts the 70% cap.
2. **Re-runnable test command** + **held-out calibration** (Step 1) — lifts two 60% caps.
3. **Coverage map + abstain on dashboard** (7c), **paraphrase test** (7d), **leakage script** (7e).
4. **Benchmark harness on 50k deck** (7h) + **speed report** (§10) + **crash/offline** (7g).
5. **AI card check** (7f) + **Step 2 prediction** — once the generator is in.
