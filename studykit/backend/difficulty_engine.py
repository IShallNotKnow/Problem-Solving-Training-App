import logging

from models import (
    Question,
    QuestionResult,
    SessionState,
    TopicEvidence,
    TopicResult,
    TopicStats,
    TopicUpdate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Difficulty controller
# ---------------------------------------------------------------------------


class DifficultyController:
    def __init__(self):
        self.K_BASE = 32.0

    def clamp(self, value, min_val, max_val):
        return max(min_val, min(max_val, value))

    def compute_evidence(
        self, tr: TopicResult, stats: TopicStats, question_difficulty: int
    ) -> TopicEvidence:
        actual_score = tr.score
        expected_score = 1 / (1 + 10 ** ((question_difficulty - stats.elo) / 400))
        p_obs = tr.confidence * tr.score + (1 - tr.confidence) * 0.5
        adaptation_scale = self.clamp(1.0 + tr.adaptation_signal, 0.25, 2.0)
        K = self.K_BASE * tr.confidence * (0.5 + 0.5 * stats.p_known) * adaptation_scale
        elo_delta = K * (actual_score - expected_score)
        return TopicEvidence(
            topic=tr.topic,
            expected_score=expected_score,
            actual_score=actual_score,
            elo_delta=elo_delta,
            p_obs=p_obs,
            adaptation_signal=tr.adaptation_signal,
            misconception=tr.misconception,
        )

    def compute_elo_update(self, stats: TopicStats, evidence: TopicEvidence) -> int:
        return int(round(self.clamp(stats.elo + evidence.elo_delta, 300, 3000)))

    def compute_bkt_update(self, stats: TopicStats, evidence: TopicEvidence) -> float:
        P_SLIP, P_GUESS, P_LEARN, P_FORGET = 0.1, 0.1, 0.1, 0.05
        p_known = stats.p_known
        p_correct = p_known * (1 - P_SLIP) + (1 - p_known) * P_GUESS
        p_if_correct = (p_known * (1 - P_SLIP)) / p_correct
        p_incorrect_denom = (p_known * P_SLIP) + (1 - p_known) * (1 - P_GUESS)
        p_if_incorrect = (p_known * P_SLIP) / p_incorrect_denom if p_incorrect_denom > 0 else 0.0
        p_posterior = (evidence.p_obs * p_if_correct) + ((1 - evidence.p_obs) * p_if_incorrect)
        return self.clamp(
            (p_posterior * (1 - P_FORGET)) + ((1 - p_posterior) * P_LEARN), 0.05, 0.95
        )

    def compute_topic_update(self, stats: TopicStats, evidence: TopicEvidence) -> TopicUpdate:
        return TopicUpdate(
            topic=evidence.topic,
            previous_elo=stats.elo,
            new_elo=self.compute_elo_update(stats, evidence),
            elo_delta=evidence.elo_delta,
            previous_p_known=stats.p_known,
            new_p_known=self.compute_bkt_update(stats, evidence),
            reason=f"score={evidence.actual_score:.2f} expected={evidence.expected_score:.2f} confidence={evidence.p_obs:.2f}",
        )

    def update(
        self, state: SessionState, result: QuestionResult, question: Question
    ) -> tuple[SessionState, list[TopicUpdate]]:
        updates = []
        for tr in result.topic_results:
            if tr.topic not in state.topic_stats:
                state.topic_stats[tr.topic] = TopicStats(topic=tr.topic)
            stats = state.topic_stats[tr.topic]
            evidence = self.compute_evidence(tr, stats, question.topic_difficulties[tr.topic])
            topic_update = self.compute_topic_update(stats, evidence)
            logger.info(
                f"[elo] topic={tr.topic} elo {stats.elo}→{topic_update.new_elo} (Δ{evidence.elo_delta:+.1f}) p_known {stats.p_known:.2f}→{topic_update.new_p_known:.2f}"
            )
            stats.elo = topic_update.new_elo
            stats.p_known = topic_update.new_p_known
            stats.attempts += 1
            updates.append(topic_update)
        state.history.append(result)
        return state, updates