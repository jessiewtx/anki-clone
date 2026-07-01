# Rust engine change — Skill-Weakness Priority Queue

## What it is
Two backend calls added to Anki's **Rust** scheduler:
- `GetSkillWeaknessQueue` — returns a deck's **fresh** due cards ordered by
  `student weakness × skill exam weight`, so weak *and* heavily-tested LSAT skills
  surface first.
- `ReorderDeckBySkillWeakness` — applies that order to the deck's new cards via
  Anki's standard reposition op, so the *normal* review order becomes concept-based.

This is deliberately **not** Anki's same-card-on-a-forgetting-curve model:

- **Skill** of a card = a note tag matching a key in the request's `skill_weights`
  map (e.g. `lsat::lr::flaw`). A card is ranked by its highest-priority skill.
- **Fresh instances only.** A problem answered correctly is *retired* and never
  re-served — otherwise the student would just memorize "the answer is C." Each time
  a concept is due, an *unsolved* problem for that concept surfaces instead.
- **Weakness** = `1 − (mastered ÷ attempts)` from the **revlog**, with a
  **response-time guard**: a "correct" answer to an exam-style problem faster than
  `MIN_PROBLEM_MILLIS` (8 s) is treated as recall/guess, not mastery. So memorizing
  an answer retires that one instance but keeps the *concept* weak — new problems keep
  coming until the student shows real, timed skill. No history → weakness 1.0.
- **Priority** = `weakness × exam_weight`; sorted descending, ties broken by
  ascending card id (deterministic).

This implements **Spiky POV 2**: the scheduler targets the reasoning skills a student
is weakest at with *novel* problems, rather than ordering by memory/decay.

## Why this belongs in Rust, not the Python UI
- **It's an engine concern.** Card ordering / scheduling lives in `rslib`'s scheduler;
  this is a new *review order*, exactly the kind of logic the engine owns.
- **Performance.** It joins three tables (cards → notes/tags → revlog) and aggregates
  per skill. In Rust with direct `storage` access this is a tight loop; doing it in
  Python would mean a backend round-trip per card and would not meet the dashboard
  speed target on 50k cards.
- **Shared across clients.** Because it's a protobuf RPC in the shared engine, the
  desktop (Python/Qt) and the phone (AnkiDroid) get the identical implementation — the
  whole point of "two apps, one engine." A Python-only version would not ship to the
  phone.

## Undo & collection integrity
`GetSkillWeaknessQueue` is **read-only**: it uses `get_deck`, `child_decks`,
`all_cards_in_single_deck`, `get_card`, `get_note`, and `get_revlog_entries_for_card`,
and creates **no transaction and writes nothing** — nothing to undo, no way to corrupt.
`ReorderDeckBySkillWeakness` *does* move cards, but it rides Anki's own `Op::SortCards`
reposition, so it is fully **undoable** and only changes new-card positions — it never
touches FSRS intervals or scheduling state. `test_reorder_by_skill_weakness.py` proves a
single `undo()` restores positions exactly.

## Tests
- **Rust unit tests** (`rslib/src/scheduler/skill_priority.rs`, run via
  `cargo test -p anki skill_priority`):
  1. `weakness_from_history` — weakness math incl. the no-history = 1.0 default.
  2. `skillstat_guards_fast_problem_answers` — response-time guard: a too-fast
     "correct" on a problem is not counted as mastery; definition cards are exempt.
  3. `ranking_orders_by_weight_times_weakness` — ordering + argmax skill selection.
  4. `ranking_tie_breaks_by_card_id_and_handles_no_skill` — deterministic ties, no-skill last.
  5. `queue_never_reshows_a_solved_problem` — a correctly-answered problem is retired.
  6. `fast_correct_retires_instance_but_keeps_concept_weak` — memorizing one answer
     retires that instance but leaves the concept weak; a real timed solve masters it.
- **Python tests** (`speedrun/tests/`, run with `out/pyenv/bin/python …`):
  - `test_skill_weakness_queue.py` — RPC returns `weakness × exam_weight` order, excludes unweighted cards.
  - `test_reorder_by_skill_weakness.py` — reposition works and a single undo restores positions (undo-safe).
- **Behavior demo** (`speedrun/scripts/demo_fresh_instance.py`): shows a solved problem
  never reappears and that a fast "correct" keeps the concept weak.

## Upstream files touched & merge difficulty
| File | Change | Merge risk |
|---|---|---|
| `proto/anki/scheduler.proto` | +2 rpcs in `SchedulerService`, +2 messages at end | **Low** — additive; only conflicts if upstream edits the same lines |
| `rslib/src/scheduler/mod.rs` | +1 line (`pub(crate) mod skill_priority;`) | **Low** — single line in the module list |
| `rslib/src/scheduler/service/mod.rs` | +2 trait methods (delegate to the new module) | **Low** — additive methods |
| `rslib/src/scheduler/skill_priority.rs` | **New file** (all the logic + tests) | **None** — new path, cannot conflict |

Overall future-merge difficulty: **low**. The substantive logic lives in a brand-new
file; the three edits to upstream files are small and additive, so rebasing onto a newer
Anki should apply cleanly in almost all cases.
