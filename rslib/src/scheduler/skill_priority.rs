// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun LSAT: a concept-mastery review order that is deliberately NOT Anki's
//! same-card-forever model.
//!
//! Two departures from stock Anki:
//! 1. **Fresh instances only.** Once a problem has been answered correctly it is
//!    *retired* — it is never re-served. Otherwise a student would just memorize
//!    "the answer is C." Each time a concept comes up, an unsolved problem for that
//!    concept surfaces instead.
//! 2. **Response-time mastery guard.** A "correct" answer to an exam-style problem
//!    faster than [`MIN_PROBLEM_MILLIS`] is treated as recall/guess, not mastery, so
//!    it does not lower the concept's weakness. Memorizing an answer therefore
//!    retires that one instance but keeps the *concept* weak, so new problems keep
//!    coming until the student shows real, timed skill.
//!
//! Priority is still `weakness × exam_weight` (weak *and* heavily-tested first).
//! The computation is read-only; `reorder_by_skill_weakness` applies the order via
//! Anki's standard, undo-safe reposition op.

use std::collections::HashMap;

use anki_proto::scheduler::skill_weakness_queue_response::Entry;
use anki_proto::scheduler::SkillWeaknessQueueResponse;

use crate::card::CardQueue;
use crate::prelude::*;
use crate::scheduler::new::NewCardDueOrder;

/// LSAT reasoning takes real time; a "correct" answer to an exam-style problem
/// faster than this is treated as recall/guess, not mastery (memorization guard).
const MIN_PROBLEM_MILLIS: u32 = 8_000;
/// Note tag marking a card as an exam-style problem (vs a plain definition card).
const PRACTICE_TAG: &str = "lsat::type::practice";

/// Aggregated review outcomes for one skill.
#[derive(Debug, Default, Clone, Copy)]
pub(crate) struct SkillStat {
    pub reviews: u32,
    pub correct: u32,
}

impl SkillStat {
    /// Record one review. For exam-style problems, a correct answer only counts as
    /// mastery if it took at least [`MIN_PROBLEM_MILLIS`]; a too-fast "correct" is
    /// counted as an attempt but not a success (the memorization guard).
    fn record(&mut self, button_chosen: u8, taken_millis: u32, is_problem: bool) {
        // 1=Again, 2=Hard, 3=Good, 4=Easy. 0 == manual reschedule; ignore it.
        if (1..=4).contains(&button_chosen) {
            self.reviews += 1;
            let too_fast = is_problem && taken_millis < MIN_PROBLEM_MILLIS;
            if button_chosen >= 2 && !too_fast {
                self.correct += 1;
            }
        }
    }
}

/// Weakness in 0.0..=1.0. No history => 1.0 (treated as maximally weak so unseen
/// skills are surfaced). Note this queue ordering is deliberately separate from
/// the readiness *score*, which has its own "not enough data" give-up rule.
pub(crate) fn weakness(stat: SkillStat) -> f32 {
    if stat.reviews == 0 {
        1.0
    } else {
        1.0 - (stat.correct as f32 / stat.reviews as f32)
    }
}

/// Everything about one candidate card that the ordering needs. Extracted from the
/// collection so the ordering logic itself is pure and unit-testable.
pub(crate) struct CardInput {
    pub card_id: i64,
    /// Skills (tags) this card exercises that have an exam weight.
    pub skills: Vec<String>,
    /// True if this is an exam-style problem (subject to the response-time guard).
    pub is_problem: bool,
    /// True if the card is currently due (new / due learning / due review).
    pub is_due: bool,
    /// (button_chosen, taken_millis) for each revlog row of this card.
    pub revlog: Vec<(u8, u32)>,
}

impl CardInput {
    /// A problem is *retired* once answered correctly at all — re-showing it would
    /// invite memorization, so it is never served again (regardless of speed).
    fn is_retired(&self) -> bool {
        self.revlog.iter().any(|(button, _)| (2..=4).contains(button))
    }
}

/// One due card together with the skills it exercises.
pub(crate) struct CardSkills {
    pub card_id: i64,
    pub skills: Vec<SkillScore>,
}

#[derive(Clone)]
pub(crate) struct SkillScore {
    pub skill: String,
    pub exam_weight: f32,
    pub weakness: f32,
}

/// Rank cards by descending priority (= max over the card's skills of
/// `weakness * exam_weight`). The skill that produced the max is reported. Ties
/// are broken by ascending card id for deterministic output.
pub(crate) fn rank_cards(cards: Vec<CardSkills>) -> Vec<Entry> {
    let mut entries: Vec<Entry> = cards
        .into_iter()
        .map(|c| {
            let best = c.skills.iter().max_by(|a, b| {
                (a.exam_weight * a.weakness)
                    .partial_cmp(&(b.exam_weight * b.weakness))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            match best {
                Some(s) => Entry {
                    card_id: c.card_id,
                    skill: s.skill.clone(),
                    weakness: s.weakness,
                    exam_weight: s.exam_weight,
                    priority: s.exam_weight * s.weakness,
                },
                None => Entry {
                    card_id: c.card_id,
                    skill: String::new(),
                    weakness: 0.0,
                    exam_weight: 0.0,
                    priority: 0.0,
                },
            }
        })
        .collect();
    entries.sort_by(|a, b| {
        b.priority
            .partial_cmp(&a.priority)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.card_id.cmp(&b.card_id))
    });
    entries
}

/// The pure ordering: per-skill weakness is aggregated across ALL of the deck's
/// history (with the response-time guard), then only *fresh* (non-retired) due
/// cards are ranked by `weakness × exam_weight`.
pub(crate) fn build_queue(cards: Vec<CardInput>, weights: &HashMap<String, f32>) -> Vec<Entry> {
    // History matters even for retired cards, so accumulate stats over everything.
    let mut stats: HashMap<String, SkillStat> = HashMap::new();
    for c in &cards {
        for skill in &c.skills {
            let stat = stats.entry(skill.clone()).or_default();
            for (button, millis) in &c.revlog {
                stat.record(*button, *millis, c.is_problem);
            }
        }
    }

    let fresh: Vec<CardSkills> = cards
        .into_iter()
        .filter(|c| c.is_due && !c.skills.is_empty() && !c.is_retired())
        .map(|c| CardSkills {
            card_id: c.card_id,
            skills: c
                .skills
                .into_iter()
                .map(|skill| {
                    let stat = stats.get(&skill).copied().unwrap_or_default();
                    let exam_weight = *weights.get(&skill).unwrap_or(&0.0);
                    SkillScore {
                        skill,
                        exam_weight,
                        weakness: weakness(stat),
                    }
                })
                .collect(),
        })
        .collect();

    rank_cards(fresh)
}

impl Collection {
    /// Build the fresh-instance concept queue for a deck (and its children).
    pub fn skill_weakness_queue(
        &mut self,
        deck_id: DeckId,
        skill_weights: &HashMap<String, f32>,
    ) -> Result<SkillWeaknessQueueResponse> {
        let mut deck_ids = vec![deck_id];
        if let Some(deck) = self.storage.get_deck(deck_id)? {
            for child in self.storage.child_decks(&deck)? {
                deck_ids.push(child.id);
            }
        }

        let mut card_ids = vec![];
        for did in &deck_ids {
            card_ids.extend(self.storage.all_cards_in_single_deck(*did)?);
        }

        let today = self.timing_today()?.days_elapsed as i32;
        let now_secs = TimestampSecs::now().0;

        let mut inputs = Vec::new();
        for cid in card_ids {
            let Some(card) = self.storage.get_card(cid)? else {
                continue;
            };
            let Some(note) = self.storage.get_note(card.note_id)? else {
                continue;
            };
            let skills: Vec<String> = note
                .tags
                .iter()
                .filter(|t| skill_weights.contains_key(t.as_str()))
                .cloned()
                .collect();
            if skills.is_empty() {
                continue;
            }
            let is_problem = note.tags.iter().any(|t| t == PRACTICE_TAG);
            let revlog: Vec<(u8, u32)> = self
                .storage
                .get_revlog_entries_for_card(cid)?
                .into_iter()
                .map(|e| (e.button_chosen, e.taken_millis))
                .collect();
            let is_due = match card.queue {
                CardQueue::New => true,
                CardQueue::Learn => (card.due as i64) <= now_secs,
                CardQueue::Review | CardQueue::DayLearn => card.due <= today,
                _ => false,
            };
            inputs.push(CardInput {
                card_id: cid.0,
                skills,
                is_problem,
                is_due,
                revlog,
            });
        }

        Ok(SkillWeaknessQueueResponse {
            entries: build_queue(inputs, skill_weights),
        })
    }

    /// Reposition the deck's NEW cards so the weakest, most heavily-weighted
    /// concepts come first, making the normal review order concept-based. This
    /// rides Anki's standard reposition op (Op::SortCards), so it is undoable
    /// and does not change FSRS intervals or corrupt scheduling state.
    pub fn reorder_by_skill_weakness(
        &mut self,
        deck_id: DeckId,
        skill_weights: &HashMap<String, f32>,
    ) -> Result<OpOutput<usize>> {
        let ranked = self.skill_weakness_queue(deck_id, skill_weights)?;
        let mut new_cids = Vec::new();
        for entry in ranked.entries {
            let cid = CardId(entry.card_id);
            if let Some(card) = self.storage.get_card(cid)? {
                if card.queue == CardQueue::New {
                    new_cids.push(cid);
                }
            }
        }
        self.sort_cards(&new_cids, 1, 1, NewCardDueOrder::Preserve, true)
    }
}

#[cfg(test)]
mod test {
    use super::*;

    fn card(id: i64, skill: &str, is_problem: bool, revlog: Vec<(u8, u32)>) -> CardInput {
        CardInput {
            card_id: id,
            skills: vec![skill.to_string()],
            is_problem,
            is_due: true,
            revlog,
        }
    }

    #[test]
    fn weakness_from_history() {
        assert_eq!(weakness(SkillStat { reviews: 0, correct: 0 }), 1.0);
        assert_eq!(weakness(SkillStat { reviews: 4, correct: 3 }), 0.25);
        assert_eq!(weakness(SkillStat { reviews: 2, correct: 2 }), 0.0);
    }

    #[test]
    fn skillstat_guards_fast_problem_answers() {
        let mut s = SkillStat::default();
        s.record(3, 10_000, true); // slow correct problem -> mastery
        s.record(3, 2_000, true); // fast correct problem -> NOT mastery (guard)
        s.record(3, 2_000, false); // fast correct definition -> counts (no guard)
        s.record(1, 30_000, true); // wrong -> attempt, not success
        s.record(0, 0, true); // manual reschedule -> ignored entirely
        assert_eq!(s.reviews, 4);
        assert_eq!(s.correct, 2);
    }

    #[test]
    fn ranking_orders_by_weight_times_weakness() {
        let cards = vec![
            CardSkills {
                card_id: 10,
                skills: vec![SkillScore {
                    skill: "weak_heavy".into(),
                    exam_weight: 0.9,
                    weakness: 0.8,
                }], // 0.72
            },
            CardSkills {
                card_id: 11,
                skills: vec![SkillScore {
                    skill: "strong_heavy".into(),
                    exam_weight: 0.9,
                    weakness: 0.1,
                }], // 0.09
            },
            CardSkills {
                card_id: 12,
                skills: vec![
                    SkillScore {
                        skill: "light".into(),
                        exam_weight: 0.1,
                        weakness: 1.0,
                    }, // 0.10
                    SkillScore {
                        skill: "mid".into(),
                        exam_weight: 0.5,
                        weakness: 0.6,
                    }, // 0.30 -> argmax
                ],
            },
        ];
        let ranked = rank_cards(cards);
        assert_eq!(ranked[0].card_id, 10); // 0.72
        assert_eq!(ranked[1].card_id, 12); // 0.30
        assert_eq!(ranked[1].skill, "mid");
        assert_eq!(ranked[2].card_id, 11); // 0.09
        assert!(ranked[0].priority > ranked[1].priority);
        assert!(ranked[1].priority > ranked[2].priority);
    }

    #[test]
    fn ranking_tie_breaks_by_card_id_and_handles_no_skill() {
        let cards = vec![
            CardSkills {
                card_id: 30,
                skills: vec![SkillScore {
                    skill: "a".into(),
                    exam_weight: 0.5,
                    weakness: 0.4,
                }],
            }, // 0.20
            CardSkills {
                card_id: 20,
                skills: vec![SkillScore {
                    skill: "b".into(),
                    exam_weight: 0.4,
                    weakness: 0.5,
                }],
            }, // 0.20 (tie)
            CardSkills {
                card_id: 40,
                skills: vec![],
            }, // 0.0 -> last
        ];
        let ranked = rank_cards(cards);
        assert_eq!(ranked[0].card_id, 20);
        assert_eq!(ranked[1].card_id, 30);
        assert_eq!(ranked[2].card_id, 40);
        assert_eq!(ranked[2].priority, 0.0);
    }

    #[test]
    fn queue_never_reshows_a_solved_problem() {
        let weights = HashMap::from([("s".to_string(), 0.5f32)]);
        let solved = card(1, "s", true, vec![(3, 10_000)]); // answered correctly -> retired
        let fresh = card(2, "s", true, vec![]); // unseen -> should be served
        let out = build_queue(vec![solved, fresh], &weights);
        assert_eq!(out.len(), 1, "the solved problem must not be re-shown");
        assert_eq!(out[0].card_id, 2);
    }

    #[test]
    fn fast_correct_retires_instance_but_keeps_concept_weak() {
        let weights = HashMap::from([("s".to_string(), 0.5f32)]);
        let queue = |a_millis: u32| {
            // A: answered correctly (retired either way); B: a fresh instance.
            let a = card(1, "s", true, vec![(3, a_millis)]);
            let b = card(2, "s", true, vec![]);
            build_queue(vec![a, b], &weights)
        };
        let fast = queue(2_000); // A answered too fast to be real mastery
        let slow = queue(20_000); // A answered with genuine reasoning time

        // Either way the solved instance A retires; the fresh instance B is served.
        assert_eq!(fast[0].card_id, 2);
        assert_eq!(slow[0].card_id, 2);
        // A fast "correct" gives no mastery credit -> concept stays maximally weak,
        // so more fresh problems keep coming.
        assert_eq!(fast[0].weakness, 1.0);
        // A genuine timed solve masters the concept -> weakness collapses.
        assert_eq!(slow[0].weakness, 0.0);
    }
}
