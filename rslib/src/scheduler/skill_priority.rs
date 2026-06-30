// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun LSAT: a "points-at-stake" review order.
//!
//! For a deck, each due card's priority is `student weakness on the card's skill
//! * the skill's exam weight`, so the highest-value (weak + heavily-tested)
//! skills surface first. Skills are read from note tags; weakness is derived
//! from the revlog.
//!
//! This is a read-only computation: it inspects cards, notes and the revlog but
//! never mutates the collection, so undo and collection integrity are
//! unaffected.

use std::collections::HashMap;

use anki_proto::scheduler::skill_weakness_queue_response::Entry;
use anki_proto::scheduler::SkillWeaknessQueueResponse;

use crate::card::CardQueue;
use crate::prelude::*;

/// Aggregated review outcomes for one skill.
#[derive(Debug, Default, Clone, Copy)]
pub(crate) struct SkillStat {
    pub reviews: u32,
    pub correct: u32,
}

impl SkillStat {
    fn record(&mut self, button_chosen: u8) {
        // 1=Again, 2=Hard, 3=Good, 4=Easy. 0 == manual reschedule; ignore it.
        if (1..=4).contains(&button_chosen) {
            self.reviews += 1;
            if button_chosen >= 2 {
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

impl Collection {
    /// Build the skill-weakness priority queue for a deck (and its children).
    pub fn skill_weakness_queue(
        &mut self,
        deck_id: DeckId,
        skill_weights: &HashMap<String, f32>,
    ) -> Result<SkillWeaknessQueueResponse> {
        // Resolve the deck and its children.
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

        // Accumulate per-skill review stats across ALL cards in the deck (history
        // matters even for cards that aren't due right now), and remember which
        // cards are currently due along with the skills they carry.
        let mut stats: HashMap<String, SkillStat> = HashMap::new();
        let mut due: Vec<(i64, Vec<String>)> = vec![];

        for cid in card_ids {
            let Some(card) = self.storage.get_card(cid)? else {
                continue;
            };
            let Some(note) = self.storage.get_note(card.note_id)? else {
                continue;
            };
            let card_skills: Vec<String> = note
                .tags
                .iter()
                .filter(|t| skill_weights.contains_key(t.as_str()))
                .cloned()
                .collect();
            if card_skills.is_empty() {
                continue;
            }

            let revlog = self.storage.get_revlog_entries_for_card(cid)?;
            for skill in &card_skills {
                let stat = stats.entry(skill.clone()).or_default();
                for e in &revlog {
                    stat.record(e.button_chosen);
                }
            }

            let is_due = match card.queue {
                CardQueue::New => true,
                CardQueue::Learn => (card.due as i64) <= now_secs,
                CardQueue::Review | CardQueue::DayLearn => card.due <= today,
                _ => false,
            };
            if is_due {
                due.push((cid.0, card_skills));
            }
        }

        let cards: Vec<CardSkills> = due
            .into_iter()
            .map(|(card_id, skills)| CardSkills {
                card_id,
                skills: skills
                    .into_iter()
                    .map(|skill| {
                        let stat = stats.get(&skill).copied().unwrap_or_default();
                        let exam_weight = *skill_weights.get(&skill).unwrap_or(&0.0);
                        SkillScore {
                            skill,
                            exam_weight,
                            weakness: weakness(stat),
                        }
                    })
                    .collect(),
            })
            .collect();

        Ok(SkillWeaknessQueueResponse {
            entries: rank_cards(cards),
        })
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn weakness_from_history() {
        assert_eq!(weakness(SkillStat { reviews: 0, correct: 0 }), 1.0);
        assert_eq!(weakness(SkillStat { reviews: 4, correct: 3 }), 0.25);
        assert_eq!(weakness(SkillStat { reviews: 2, correct: 2 }), 0.0);
    }

    #[test]
    fn skillstat_records_only_real_buttons() {
        let mut s = SkillStat::default();
        for b in [1u8, 2, 3, 4, 0] {
            s.record(b);
        }
        // 0 (manual) ignored; 1 wrong; 2/3/4 correct.
        assert_eq!(s.reviews, 4);
        assert_eq!(s.correct, 3);
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
        // Tie at 0.20 broken by ascending card id: 20 before 30.
        assert_eq!(ranked[0].card_id, 20);
        assert_eq!(ranked[1].card_id, 30);
        assert_eq!(ranked[2].card_id, 40);
        assert_eq!(ranked[2].priority, 0.0);
    }
}
