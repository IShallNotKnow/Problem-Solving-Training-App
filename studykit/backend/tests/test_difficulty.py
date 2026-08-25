from backend.difficulty_engine import DifficultyController
from backend.models import TopicResult, TopicStats


def test_bkt_update():
    dc = DifficultyController()

    # A correct answer should increase p_known
    stats = TopicStats(topic="calculus", elo=1500, p_known=0.5, attempts=5)
    evidence_correct = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=1.0,
            correct=True,
            confidence=0.9,
            adaptation_signal=1.0,
            misconception=None,
            feedback="Correct!",
        ),
        stats,
        question_difficulty=1500,
    )
    p_after_correct = dc.compute_bkt_update(stats, evidence_correct)
    assert p_after_correct > stats.p_known, (
        f"Correct answer should increase p_known: {stats.p_known} -> {p_after_correct}"
    )

    # An incorrect answer should decrease p_known
    evidence_incorrect = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=0.0,
            correct=False,
            confidence=0.9,
            adaptation_signal=-1.0,
            misconception=None,
            feedback="Incorrect.",
        ),
        stats,
        question_difficulty=1500,
    )
    p_after_incorrect = dc.compute_bkt_update(stats, evidence_incorrect)
    assert p_after_incorrect < stats.p_known, (
        f"Incorrect answer should decrease p_known: {stats.p_known} -> {p_after_incorrect}"
    )

    # p_known should never exceed 0.95 (upper bound)
    stats_high = TopicStats(topic="calculus", elo=1500, p_known=0.94, attempts=20)
    evidence_high = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=1.0,
            correct=True,
            confidence=1.0,
            adaptation_signal=1.0,
            misconception=None,
            feedback="Correct!",
        ),
        stats_high,
        question_difficulty=1500,
    )
    p_clamped_high = dc.compute_bkt_update(stats_high, evidence_high)
    assert p_clamped_high <= 0.95, f"p_known should not exceed 0.95: got {p_clamped_high}"

    # p_known should never fall below 0.05 (lower bound)
    stats_low = TopicStats(topic="calculus", elo=1500, p_known=0.06, attempts=0)
    evidence_low = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=0.0,
            correct=False,
            confidence=1.0,
            adaptation_signal=-1.0,
            misconception=None,
            feedback="Incorrect.",
        ),
        stats_low,
        question_difficulty=1500,
    )
    p_clamped_low = dc.compute_bkt_update(stats_low, evidence_low)
    assert p_clamped_low >= 0.05, f"p_known should not fall below 0.05: got {p_clamped_low}"

    # Forgetting: repeated incorrect answers on a high p_known student
    # should meaningfully reduce p_known, not plateau near 1
    stats_forgetting = TopicStats(topic="calculus", elo=1500, p_known=0.8, attempts=10)
    p = stats_forgetting.p_known
    for _ in range(5):
        ev = dc.compute_evidence(
            TopicResult(
                topic="calculus",
                score=0.0,
                correct=False,
                confidence=0.9,
                adaptation_signal=-1.0,
                misconception=None,
                feedback="Incorrect.",
            ),
            TopicStats(topic="calculus", elo=1500, p_known=p, attempts=10),
            question_difficulty=1500,
        )
        p = dc.compute_bkt_update(
            TopicStats(topic="calculus", elo=1500, p_known=p, attempts=10), ev
        )
    assert p < 0.8, f"Repeated incorrect answers should reduce p_known below initial 0.8, got {p}"


def test_elo_update():
    dc = DifficultyController()

    # Correct answer on a question at exactly the student's ELO
    # should increase ELO
    stats = TopicStats(topic="calculus", elo=1500, p_known=0.5, attempts=5)
    evidence_correct = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=1.0,
            correct=True,
            confidence=1.0,
            adaptation_signal=1.0,
            misconception=None,
            feedback="Correct!",
        ),
        stats,
        question_difficulty=1500,
    )
    new_elo = dc.compute_elo_update(stats, evidence_correct)
    assert new_elo > stats.elo, (
        f"Correct answer at matched difficulty should increase ELO: {stats.elo} -> {new_elo}"
    )

    # Incorrect answer on a question at exactly the student's ELO
    # should decrease ELO
    evidence_incorrect = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=0.0,
            correct=False,
            confidence=1.0,
            adaptation_signal=-1.0,
            misconception=None,
            feedback="Incorrect.",
        ),
        stats,
        question_difficulty=1500,
    )
    new_elo_incorrect = dc.compute_elo_update(stats, evidence_incorrect)
    assert new_elo_incorrect < stats.elo, (
        f"Incorrect answer at matched difficulty should decrease ELO: {stats.elo} -> {new_elo_incorrect}"
    )

    # Monotonicity: higher score on same question should always yield higher ELO delta
    scores = [0.0, 0.25, 0.5, 0.75, 1.0]
    elo_results = []
    for score in scores:
        ev = dc.compute_evidence(
            TopicResult(
                topic="calculus",
                score=score,
                correct=score == 1.0,
                confidence=1.0,
                adaptation_signal=score - 0.5,
                misconception=None,
                feedback="",
            ),
            stats,
            question_difficulty=1500,
        )
        elo_results.append(dc.compute_elo_update(stats, ev))
    assert elo_results == sorted(elo_results), (
        f"ELO updates should be monotonically increasing with score: {list(zip(scores, elo_results))}"
    )

    # ELO should never exceed 3000
    stats_high = TopicStats(topic="calculus", elo=2990, p_known=0.9, attempts=50)
    ev_high = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=1.0,
            correct=True,
            confidence=1.0,
            adaptation_signal=1.0,
            misconception=None,
            feedback="Correct!",
        ),
        stats_high,
        question_difficulty=1500,
    )
    assert dc.compute_elo_update(stats_high, ev_high) <= 3000, "ELO should be clamped at 3000"

    # ELO should never fall below 300
    stats_low = TopicStats(topic="calculus", elo=310, p_known=0.1, attempts=0)
    ev_low = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=0.0,
            correct=False,
            confidence=1.0,
            adaptation_signal=-1.0,
            misconception=None,
            feedback="Incorrect.",
        ),
        stats_low,
        question_difficulty=1500,
    )
    assert dc.compute_elo_update(stats_low, ev_low) >= 300, "ELO should be clamped at 300"

    # Answering an easy question correctly (well below student ELO)
    # should yield a smaller ELO gain than answering a hard question correctly
    ev_easy = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=1.0,
            correct=True,
            confidence=1.0,
            adaptation_signal=1.0,
            misconception=None,
            feedback="Correct!",
        ),
        stats,
        question_difficulty=800,  # much easier than student's 1500
    )
    ev_hard = dc.compute_evidence(
        TopicResult(
            topic="calculus",
            score=1.0,
            correct=True,
            confidence=1.0,
            adaptation_signal=1.0,
            misconception=None,
            feedback="Correct!",
        ),
        stats,
        question_difficulty=2200,  # much harder than student's 1500
    )
    gain_easy = dc.compute_elo_update(stats, ev_easy) - stats.elo
    gain_hard = dc.compute_elo_update(stats, ev_hard) - stats.elo
    assert gain_hard > gain_easy, (
        f"Correctly answering a harder question should yield more ELO: easy={gain_easy}, hard={gain_hard}"
    )
