"""Generic string-similarity primitives used to tolerate typos in shopper
queries. Nothing here knows about products, brands, or categories -- it
only compares strings. Keeping it dependency-free (pure stdlib) avoids
pulling in a native-compiled fuzzy-matching package for a buildathon demo.
"""

from difflib import SequenceMatcher
from functools import lru_cache


@lru_cache(maxsize=4096)
def levenshtein_distance(left: str, right: str) -> int:
    """Classic edit distance (insert/delete/substitute), memoized because
    the same short tokens get compared against many catalog words per
    request."""

    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous_row = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current_row = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = previous_row[j] + 1
            substitute_cost = previous_row[j - 1] + (left_char != right_char)
            current_row.append(min(insert_cost, delete_cost, substitute_cost))
        previous_row = current_row

    return previous_row[-1]


def similarity_ratio(left: str, right: str) -> float:
    """A 0..1 similarity score (Ratcliff/Obershelp). Used as a soft signal
    layered on top of edit distance -- good at rewarding partial/substring
    matches like "iphon" vs "iphone" beyond a raw distance count."""

    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def max_allowed_distance(token_length: int) -> int:
    """How many typo'd characters we tolerate, scaled to word length so a
    3-letter word doesn't match half the dictionary."""

    if token_length <= 3:
        return 0
    if token_length <= 5:
        return 1
    if token_length <= 8:
        return 2
    return 3


def is_fuzzy_match(query_token: str, candidate: str) -> bool:
    """True when `query_token` is close enough to `candidate` to be
    considered the same word (typo tolerance), or one is a prefix of the
    other (handles a user trailing off mid-word, e.g. "iphon")."""

    if not query_token or not candidate:
        return False
    if query_token == candidate:
        return True

    allowed = max_allowed_distance(max(len(query_token), len(candidate)))

    if (
        len(query_token) >= 3
        and abs(len(query_token) - len(candidate)) <= allowed
        and (candidate.startswith(query_token) or query_token.startswith(candidate))
    ):
        # Bounded by the same tolerance as the edit-distance check below,
        # so "blue" doesn't count as a prefix match of "bluetooth" (5
        # extra characters is not a plausible typo) while "iphon" still
        # matches "iphone" (a 1-character trail-off).
        return True

    distance = levenshtein_distance(query_token, candidate)
    return distance <= allowed


def best_fuzzy_match(
    query_token: str,
    candidates,
) -> tuple[str, float] | None:
    """Best-scoring candidate word for `query_token`, or None when nothing
    is close enough. Score blends distance-based tolerance with the
    Ratcliff/Obershelp ratio so ties favor the more visually similar word."""

    best_candidate: str | None = None
    best_score = -1.0

    for candidate in candidates:
        if not candidate:
            continue
        if not is_fuzzy_match(query_token, candidate):
            continue
        score = similarity_ratio(query_token, candidate)
        if candidate == query_token:
            score = 1.0
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is None:
        return None
    return best_candidate, best_score
