import math

import pytest
from backend.scheduler import (
    TARGET_RETENTION,
    W,
    clamp,
    difficulty_update,
    fsrs_update,
    initial_difficulty,
    initial_stability,
    next_interval,
    retrievability,
    score_to_fsrs_rating,
    update_stability,
    update_stability_short_term,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def assert_close(actual: float, expected: float, *, rel=1e-6, abs_=1e-6):
    assert math.isclose(actual, expected, rel_tol=rel, abs_tol=abs_), (
        f"expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# clamp
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.0, 1.0),
        (0.5, 1.0),
        (1.0, 1.0),
        (1.000001, 1.000001),
        (5.0, 5.0),
        (9.999999, 9.999999),
        (10.0, 10.0),
        (10.000001, 10.0),
        (100.0, 10.0),
    ],
)
def test_clamp(value, expected):
    assert_close(clamp(value), expected)


# ---------------------------------------------------------------------------
# score_to_fsrs_rating
# ---------------------------------------------------------------------------


def test_score_to_fsrs_rating_boundaries():
    assert score_to_fsrs_rating(0.0) == 1
    assert score_to_fsrs_rating(0.399999) == 1

    assert score_to_fsrs_rating(0.4) == 2
    assert score_to_fsrs_rating(0.699999) == 2

    assert score_to_fsrs_rating(0.7) == 3
    assert score_to_fsrs_rating(0.899999) == 3

    assert score_to_fsrs_rating(0.9) == 4
    assert score_to_fsrs_rating(1.0) == 4


@pytest.mark.parametrize(
    "score, expected_rating",
    [
        (-1.0, 1),
        (0.0, 1),
        (0.1, 1),
        (0.5, 2),
        (0.8, 3),
        (1.0, 4),
        (1.5, 4),
        (float("-inf"), 1),
        (float("inf"), 4),
    ],
)
def test_score_to_fsrs_rating_general_values(score, expected_rating):
    assert score_to_fsrs_rating(score) == expected_rating


# ---------------------------------------------------------------------------
# initial_stability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rating, expected",
    [
        (1, W[0]),
        (2, W[1]),
        (3, W[2]),
        (4, W[3]),
    ],
)
def test_initial_stability(rating, expected):
    assert_close(initial_stability(rating), expected)


def test_initial_stability_increases_with_rating():
    values = [initial_stability(rating) for rating in range(1, 5)]

    assert values == sorted(values)
    assert len(set(values)) == 4


def test_initial_stability_is_positive():
    for rating in range(1, 5):
        assert initial_stability(rating) > 0


# ---------------------------------------------------------------------------
# initial_difficulty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rating, expected",
    [
        (1, 8.2734),
        (2, 7.7418),
        (3, 7.2102),
        (4, 6.6786),
    ],
)
def test_initial_difficulty(rating, expected):
    assert_close(initial_difficulty(rating), expected)


def test_initial_difficulty_decreases_with_easier_rating():
    difficulties = [initial_difficulty(rating) for rating in range(1, 5)]

    assert difficulties == sorted(difficulties, reverse=True)


def test_initial_difficulty_is_within_valid_range():
    for rating in range(1, 5):
        difficulty = initial_difficulty(rating)

        assert 1.0 <= difficulty <= 10.0


# ---------------------------------------------------------------------------
# retrievability
# ---------------------------------------------------------------------------


def test_retrievability_at_zero_days_is_one():
    assert_close(retrievability(0, 10), 1.0)


@pytest.mark.parametrize(
    "days, stability, expected",
    [
        (0, 10, 1.0),
        (10, 10, 0.3214285714285714),
        (20, 10, 0.19148936170212766),
        (5, 5, 0.3214285714285714),
    ],
)
def test_retrievability(days, stability, expected):
    assert_close(retrievability(days, stability), expected)


def test_retrievability_decreases_as_time_passes():
    values = [retrievability(days, 10) for days in [0, 1, 5, 10, 20, 50, 100]]

    assert all(values[i] > values[i + 1] for i in range(len(values) - 1))


def test_retrievability_is_between_zero_and_one():
    for days in [0, 1, 5, 10, 100]:
        value = retrievability(days, 10)

        assert 0.0 < value <= 1.0


def test_retrievability_scales_with_days_and_stability():
    # Same days/stability ratio should produce the same result.
    assert_close(
        retrievability(5, 5),
        retrievability(10, 10),
    )


def test_retrievability_increases_with_stability():
    days = 10

    low = retrievability(days, 5)
    high = retrievability(days, 10)

    assert high > low


# ---------------------------------------------------------------------------
# next_interval
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stability, expected",
    [
        (1, 0.05263157894736842),
        (5, 0.2631578947368421),
        (10, 0.5263157894736842),
        (15.4722, 0.8143263157894737),
    ],
)
def test_next_interval(stability, expected):
    assert_close(next_interval(stability), expected)


def test_next_interval_is_proportional_to_stability():
    i1 = next_interval(5)
    i2 = next_interval(10)

    assert_close(i2 / i1, 2.0)


def test_next_interval_is_monotonically_increasing():
    stabilities = [1, 5, 10, 20, 50]
    intervals = [next_interval(s) for s in stabilities]

    assert all(intervals[i] < intervals[i + 1] for i in range(len(intervals) - 1))


def test_next_interval_uses_target_retention():
    stability = 10

    expected = (9 / 19) * stability * (TARGET_RETENTION**-1 - 1)

    assert_close(next_interval(stability), expected)


def test_next_interval_is_positive():
    for stability in [1, 5, 10, 20, 50]:
        assert next_interval(stability) > 0


# ---------------------------------------------------------------------------
# difficulty_update
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "difficulty, rating, expected",
    [
        (5.0, 1, 7.134912),
        (7.0, 1, 9.017112),
        (5.0, 2, 6.132546),
        (7.0, 2, 8.014746),
        (5.0, 3, 5.130181),
        (7.0, 3, 7.012381),
        (5.0, 4, 4.127815),
        (7.0, 4, 6.010015),
    ],
)
def test_difficulty_update(difficulty, rating, expected):
    assert_close(
        difficulty_update(difficulty, rating),
        expected,
    )


def test_difficulty_update_easier_rating_reduces_difficulty():
    difficulty = 7.0

    again = difficulty_update(difficulty, 1)
    hard = difficulty_update(difficulty, 2)
    good = difficulty_update(difficulty, 3)
    easy = difficulty_update(difficulty, 4)

    assert easy < good < hard < again


def test_difficulty_update_rating_ordering():
    difficulty = 7.0

    values = [difficulty_update(difficulty, rating) for rating in range(1, 5)]

    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("difficulty", [1.0, 2.0, 5.0, 8.0, 10.0])
@pytest.mark.parametrize("rating", [1, 2, 3, 4])
def test_difficulty_update_is_within_valid_range(difficulty, rating):
    result = difficulty_update(difficulty, rating)

    assert 1.0 <= result <= 10.0


def test_difficulty_update_moves_toward_baseline():
    baseline = initial_difficulty(3)

    low = difficulty_update(2.0, 3)
    high = difficulty_update(9.0, 3)

    assert low > 2.0
    assert high < 9.0

    assert low <= baseline
    assert high >= baseline


def test_difficulty_update_at_boundary_values():
    for difficulty in [1.0, 10.0]:
        for rating in range(1, 5):
            result = difficulty_update(difficulty, rating)

            assert 1.0 <= result <= 10.0


# ---------------------------------------------------------------------------
# update_stability_short_term
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rating, expected",
    [
        (1, 4.296149),
        (2, 10.0),
        (3, 11.914059),
        (4, 19.840377),
    ],
)
def test_update_stability_short_term(rating, expected):
    assert_close(
        update_stability_short_term(10.0, rating),
        expected,
    )


def test_short_term_stability_increases_with_rating():
    values = [update_stability_short_term(10.0, rating) for rating in range(1, 5)]

    assert values == sorted(values)
    assert len(set(values)) == 4


def test_short_term_again_reduces_stability():
    old_stability = 10.0

    new_stability = update_stability_short_term(
        old_stability,
        1,
    )

    assert new_stability < old_stability


def test_short_term_hard_never_reduces_stability():
    old_stability = 10.0

    new_stability = update_stability_short_term(
        old_stability,
        2,
    )

    assert new_stability >= old_stability


def test_short_term_good_increases_stability():
    old_stability = 10.0

    new_stability = update_stability_short_term(
        old_stability,
        3,
    )

    assert new_stability > old_stability


def test_short_term_easy_increases_stability():
    old_stability = 10.0

    new_stability = update_stability_short_term(
        old_stability,
        4,
    )

    assert new_stability > old_stability


# ---------------------------------------------------------------------------
# update_stability - long term
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rating, expected",
    [
        (1, 7.615831),
        (2, 0.0),
        (3, 66.445548),
        (4, 198.658898),
    ],
)
def test_update_stability_long_term(rating, expected):
    r = retrievability(10, 10)

    assert_close(
        update_stability(
            stability=10.0,
            difficulty=5.0,
            r=r,
            rating=rating,
        ),
        expected,
    )


def test_long_term_again_does_not_increase_stability():
    r = retrievability(5, 10)

    new_stability = update_stability(
        stability=10.0,
        difficulty=5.0,
        r=r,
        rating=1,
    )

    assert new_stability <= 10.0


def test_long_term_good_increases_stability():
    r = retrievability(10, 10)

    new_stability = update_stability(
        stability=10.0,
        difficulty=5.0,
        r=r,
        rating=3,
    )

    assert new_stability > 10.0


def test_long_term_easy_increases_stability_more_than_good():
    r = retrievability(10, 10)

    good = update_stability(
        stability=10.0,
        difficulty=5.0,
        r=r,
        rating=3,
    )

    easy = update_stability(
        stability=10.0,
        difficulty=5.0,
        r=r,
        rating=4,
    )

    assert easy > good


def test_long_term_stability_good_less_than_easy():
    r = retrievability(10, 10)

    values = [
        update_stability(
            stability=10.0,
            difficulty=5.0,
            r=r,
            rating=rating,
        )
        for rating in [3, 4]
    ]

    assert values[0] < values[1]


# ---------------------------------------------------------------------------
# fsrs_update
# ---------------------------------------------------------------------------


def test_fsrs_update_short_term():
    stability, difficulty, interval = fsrs_update(
        stability=5.0,
        difficulty=5.0,
        days_since_attempt=0.5,
        rating=3,
    )

    assert_close(stability, 5.957029)
    assert_close(difficulty, 5.130181)
    assert_close(interval, 0.313528)


def test_fsrs_update_long_term_good():
    stability, difficulty, interval = fsrs_update(
        stability=10.0,
        difficulty=5.0,
        days_since_attempt=10.0,
        rating=3,
    )

    assert_close(stability, 65.220860)
    assert_close(difficulty, 5.130181)
    assert_close(interval, 3.432677)


def test_fsrs_update_long_term_again():
    stability, difficulty, interval = fsrs_update(
        stability=10.0,
        difficulty=5.0,
        days_since_attempt=10.0,
        rating=1,
    )

    assert_close(stability, 7.323712)
    assert_close(difficulty, 7.134912)
    assert_close(interval, 0.385459)


def test_fsrs_update_long_term_easy():
    stability, difficulty, interval = fsrs_update(
        stability=10.0,
        difficulty=5.0,
        days_since_attempt=10.0,
        rating=4,
    )

    assert_close(stability, 223.190681)
    assert_close(difficulty, 4.127815)
    assert_close(interval, 11.746878)


@pytest.mark.parametrize("rating", [1, 2, 3, 4])
def test_fsrs_update_produces_valid_result_for_every_rating(rating):
    stability, difficulty, interval = fsrs_update(
        stability=10.0,
        difficulty=5.0,
        days_since_attempt=10.0,
        rating=rating,
    )

    assert math.isfinite(stability)
    assert math.isfinite(difficulty)
    assert math.isfinite(interval)

    assert stability >= 0.0
    assert 1.0 <= difficulty <= 10.0
    assert interval >= 0.0


def test_fsrs_update_uses_short_term_path_before_one_day():
    old_stability = 5.0
    old_difficulty = 5.0

    result = fsrs_update(
        old_stability,
        old_difficulty,
        0.5,
        3,
    )

    expected_stability = update_stability_short_term(
        old_stability,
        3,
    )
    expected_difficulty = difficulty_update(
        old_difficulty,
        3,
    )

    assert_close(result[0], expected_stability)
    assert_close(result[1], expected_difficulty)
    assert_close(result[2], next_interval(expected_stability))


def test_fsrs_update_boundary_below_one_day():
    old_stability = 10.0
    old_difficulty = 5.0
    days = 0.999999
    rating = 3

    result = fsrs_update(
        old_stability,
        old_difficulty,
        days,
        rating,
    )

    expected_stability = update_stability_short_term(
        old_stability,
        rating,
    )
    expected_difficulty = difficulty_update(
        old_difficulty,
        rating,
    )

    assert_close(result[0], expected_stability)
    assert_close(result[1], expected_difficulty)
    assert_close(result[2], next_interval(expected_stability))


def test_fsrs_update_uses_long_term_path_at_one_day():
    old_stability = 10.0
    old_difficulty = 5.0
    days = 1.0
    rating = 3

    new_stability, new_difficulty, interval = fsrs_update(
        old_stability,
        old_difficulty,
        days,
        rating,
    )

    expected_difficulty = difficulty_update(
        old_difficulty,
        rating,
    )

    r = retrievability(days, old_stability)

    expected_stability = update_stability(
        old_stability,
        expected_difficulty,
        r,
        rating,
    )

    assert_close(new_difficulty, expected_difficulty)
    assert_close(new_stability, expected_stability)
    assert_close(interval, next_interval(expected_stability))


def test_fsrs_update_at_zero_days():
    old_stability = 5.0
    old_difficulty = 5.0
    rating = 3

    stability, difficulty, interval = fsrs_update(
        old_stability,
        old_difficulty,
        0.0,
        rating,
    )

    expected_stability = update_stability_short_term(
        old_stability,
        rating,
    )
    expected_difficulty = difficulty_update(
        old_difficulty,
        rating,
    )

    assert_close(stability, expected_stability)
    assert_close(difficulty, expected_difficulty)
    assert_close(interval, next_interval(expected_stability))


# ---------------------------------------------------------------------------
# End-to-end / sequence tests
# ---------------------------------------------------------------------------


def test_new_good_card_can_be_scheduled():
    stability = initial_stability(3)
    difficulty = initial_difficulty(3)

    interval = next_interval(stability)

    assert stability > 0
    assert 1.0 <= difficulty <= 10.0
    assert interval > 0


def test_realistic_good_review_sequence():
    stability = initial_stability(3)
    difficulty = initial_difficulty(3)

    first_interval = next_interval(stability)

    new_stability, new_difficulty, next_review = fsrs_update(
        stability,
        difficulty,
        first_interval,
        3,
    )

    assert_close(stability, 3.1262)
    assert_close(difficulty, 7.2102)
    assert_close(first_interval, 0.164537)

    assert_close(new_stability, 3.724573)
    assert_close(new_difficulty, 7.2102)
    assert_close(next_review, 0.196030)

    assert new_stability > stability
    assert next_review > first_interval


def test_again_review_reduces_stability():
    stability = 10.0
    difficulty = 5.0
    days = 10.0

    new_stability, new_difficulty, interval = fsrs_update(
        stability,
        difficulty,
        days,
        1,
    )

    assert new_stability < stability
    assert new_difficulty > difficulty
    assert interval > 0


def test_easy_review_increases_stability_and_reduces_difficulty():
    stability = 10.0
    difficulty = 5.0

    new_stability, new_difficulty, interval = fsrs_update(
        stability,
        difficulty,
        10.0,
        4,
    )

    assert new_stability > stability
    assert new_difficulty < difficulty
    assert interval > 0


def test_repeated_good_reviews_increase_stability():
    stability = initial_stability(3)
    difficulty = initial_difficulty(3)

    stabilities = [stability]
    intervals = []

    for _ in range(10):
        interval = next_interval(stability)
        intervals.append(interval)

        stability, difficulty, _ = fsrs_update(
            stability,
            difficulty,
            interval,
            3,
        )

        stabilities.append(stability)

    assert all(stabilities[i] < stabilities[i + 1] for i in range(len(stabilities) - 1))


def test_repeated_good_reviews_increase_intervals():
    stability = initial_stability(3)
    difficulty = initial_difficulty(3)

    intervals = []

    for _ in range(10):
        interval = next_interval(stability)
        intervals.append(interval)

        stability, difficulty, _ = fsrs_update(
            stability,
            difficulty,
            interval,
            3,
        )

    assert all(intervals[i] < intervals[i + 1] for i in range(len(intervals) - 1))


def test_good_then_again_reduces_stability():
    stability = initial_stability(3)
    difficulty = initial_difficulty(3)

    # First successful review.
    interval = next_interval(stability)

    stability, difficulty, _ = fsrs_update(
        stability,
        difficulty,
        interval,
        3,
    )

    stability_after_good = stability

    # Later failed review.
    stability, difficulty, _ = fsrs_update(
        stability,
        difficulty,
        10.0,
        1,
    )

    assert stability <= stability_after_good
    assert difficulty > initial_difficulty(3)


@pytest.mark.parametrize(
    "stability, difficulty, days",
    [
        (1.0, 5.0, 1.0),
        (3.0, 7.0, 5.0),
        (10.0, 5.0, 10.0),
        (50.0, 3.0, 30.0),
    ],
)
def test_again_never_increases_stability(stability, difficulty, days):
    r = retrievability(days, stability)

    new_stability = update_stability(
        stability,
        difficulty,
        r,
        1,
    )

    assert new_stability <= stability


def test_all_ratings_produce_valid_end_to_end_results():
    for rating in range(1, 5):
        stability = initial_stability(3)
        difficulty = initial_difficulty(3)
        interval = next_interval(stability)

        new_stability, new_difficulty, next_interval_value = fsrs_update(
            stability,
            difficulty,
            interval,
            rating,
        )

        assert math.isfinite(new_stability)
        assert math.isfinite(new_difficulty)
        assert math.isfinite(next_interval_value)

        assert new_stability >= 0.0
        assert 1.0 <= new_difficulty <= 10.0
        assert next_interval_value >= 0.0
