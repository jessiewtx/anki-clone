# Rust engine change — Skill-Weakness Priority Queue

## What it is
A new backend call, `GetSkillWeaknessQueue`, added to Anki's **Rust** scheduler. For
a deck it returns that deck's **due cards ordered by `student weakness × skill exam
weight`**, so the highest-value (weak *and* heavily-tested) LSAT skills surface first.

- **Skill** of a card = a note tag that matches a key in the request's
  `skill_weights` map (e.g. `lsat::lr::necessary_assumption`). A card may carry
  several skills; it is ranked by the one with the highest priority.
- **Weakness** of a skill = `1 − (correct ÷ reviews)` aggregated from the **revlog**
  across the deck (a press of *Again* counts as incorrect; *Hard/Good/Easy* count as
  correct; manual reschedules are ignored). A skill with **no history → weakness 1.0**
  (surfaced for coverage). This queue ordering is intentionally separate from the
  readiness *score*, which keeps its own "not enough data" give-up rule.
- **Priority** = `weakness × exam_weight`; entries are returned sorted descending,
  ties broken by ascending card id (deterministic).

This implements **Spiky POV 2**: rethinking the scheduler so it targets the reasoning
skills a student is weakest at, rather than ordering purely by memory/decay.

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
The call is **read-only**: it uses `get_deck`, `child_decks`, `all_cards_in_single_deck`,
`get_card`, `get_note`, and `get_revlog_entries_for_card`, and creates **no transaction
and writes nothing**. There is therefore nothing to undo and no way for it to corrupt
the collection. (The earlier `studied_today` marker is the only other engine edit and is
likewise non-mutating.)

## Tests
- **Rust unit tests** (`rslib/src/scheduler/skill_priority.rs`, run via
  `cargo test -p anki skill_priority`):
  1. `weakness_from_history` — weakness math incl. the no-history = 1.0 default.
  2. `skillstat_records_only_real_buttons` — Again/Hard/Good/Easy counted, manual ignored.
  3. `ranking_orders_by_weight_times_weakness` — ordering + argmax skill selection.
  4. `ranking_tie_breaks_by_card_id_and_handles_no_skill` — deterministic ties, no-skill last.
- **Python test** (`speedrun/tests/test_skill_weakness_queue.py`, run with
  `out/pyenv/bin/python …`): builds a collection, adds skill-tagged cards, calls
  `col._backend.get_skill_weakness_queue(...)`, and asserts the returned order is
  `weakness × exam_weight` descending and that unweighted cards are excluded.

## Upstream files touched & merge difficulty
| File | Change | Merge risk |
|---|---|---|
| `proto/anki/scheduler.proto` | +1 rpc in `SchedulerService`, +2 messages at end | **Low** — additive; only conflicts if upstream edits the same lines |
| `rslib/src/scheduler/mod.rs` | +1 line (`pub(crate) mod skill_priority;`) | **Low** — single line in the module list |
| `rslib/src/scheduler/service/mod.rs` | +1 trait method (delegates to the new module) | **Low** — additive method |
| `rslib/src/scheduler/skill_priority.rs` | **New file** (all the logic + tests) | **None** — new path, cannot conflict |

Overall future-merge difficulty: **low**. The substantive logic lives in a brand-new
file; the three edits to upstream files are small and additive, so rebasing onto a newer
Anki should apply cleanly in almost all cases.
