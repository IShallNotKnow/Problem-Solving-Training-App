import math

# Default FSRS5 weights
W = [
    0.4072,
    1.1829,
    3.1262,
    15.4722,
    7.2102,
    0.5316,
    1.0651,
    0.0589,
    0.3142,
    0.1544,
    1.0070,
    1.9395,
    0.1100,
    0.2900,
    2.2700,
    0.0000,
    2.9898,
    0.5100,
    0.3434,
    1.3110,
    0.2191,
    0.1009,
]

TARGET_RETENTION = 0.9


def clamp(val):
    return max(1.0, min(10.0, val))


def retrievability(days_since_attempt: float, stability: float) -> float:
    return (1 + (19 / 9) * (days_since_attempt / stability)) ** -1


def score_to_fsrs_rating(score: float) -> int:
    if score < 0.4:
        return 1  # Again
    if score < 0.7:
        return 2  # Hard
    if score < 0.9:
        return 3  # Good
    return 4  # Easy


def initial_stability(rating: int) -> float:
    # rating 1=Again, 2=Hard, 3=Good, 4=Easy
    return W[rating - 1]  # W[0] through W[3]


def initial_difficulty(rating: int) -> float:
    # W[4]=7.21, W[5]=0.53
    # Again: 7.21 + 1.06 = 8.27  (hard card)
    # Hard:  7.21 + 0.53 = 7.74
    # Good:  7.21          = 7.21  (average)
    # Easy:  7.21 - 0.53  = 6.68  (easy card)
    difficulty_init = W[4] - (rating - 3) * W[5]
    return clamp(difficulty_init)


def next_interval(stability: float) -> float:
    return (9 / 19) * stability * (TARGET_RETENTION**-1 - 1)


def difficulty_update(difficulty: float, rating: int) -> float:
    delta_d = -W[6] * (rating - 3)
    new_d = difficulty + delta_d
    new_d = W[7] * initial_difficulty(3) + (1 - W[7]) * new_d
    return clamp(new_d)


def update_stability(stability: float, difficulty: float, r: float, rating: int) -> float:
    if rating == 1:
        s_f = (
            W[11]
            * (difficulty ** -W[12])
            * ((stability + 1) ** W[13] - 1)
            * math.exp(W[14] * (1 - r))
        )
        return min(s_f, stability)
    else:
        modifier = W[15] if rating == 2 else (W[16] if rating == 4 else 1.0)
        factor = 1 + math.exp(W[8]) * (11 - difficulty) * (stability ** -W[9]) * (
            math.exp(W[10] * (1 - r)) - 1
        )
        return stability * factor * modifier


def update_stability_short_term(stability: float, rating: int) -> float:
    new_stability = stability * math.exp(W[17] * (rating - 3 + W[18]))
    if rating >= 2:
        return max(new_stability, stability)
    return new_stability


def fsrs_update(
    stability: float,
    difficulty: float,
    days_since_attempt: float,
    rating: int,
) -> tuple[float, float, float]:

    new_difficulty = difficulty_update(difficulty, rating)
    r = retrievability(days_since_attempt, stability)

    if days_since_attempt < 1:
        new_stability = update_stability_short_term(stability, rating)
    else:
        new_stability = update_stability(stability, new_difficulty, r, rating)

    interval = next_interval(new_stability)
    return new_stability, new_difficulty, interval
