# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""Evaluation metrics for eval-gated releases.

Everything here is deterministic and dependency-light (numpy/num2words only)
so it runs in CI and on this laptop. Model-specific runners live in
evals.runners and may require the optional ``speech`` extras.
"""

from __future__ import annotations

import math
import re
import unicodedata

from num2words import num2words

# ---------------------------------------------------------------------------
# Text normalization (German)
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\säöüÄÖÜß]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_DIGIT_RE = re.compile(r"\d+")


def normalize_german(text: str) -> str:
    """Normalize German text for fair WER comparison.

    - Unicode NFKC, casefold
    - punctuation removed (phone-quality transcripts have unreliable punctuation)
    - digit runs expanded to German number words, because callers dictate
      numbers ("vierundzwanzig") while references may write digits ("24")
    """
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _DIGIT_RE.sub(lambda m: num2words(int(m.group(0)), lang="de"), text)
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate via Levenshtein alignment on normalized words. 0.0 = perfect."""
    ref = normalize_german(reference).split()
    hyp = normalize_german(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    # Classic DP edit distance; utterances are short so O(n*m) is fine.
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cur[j] = min(
                prev[j] + 1,  # deletion
                cur[j - 1] + 1,  # insertion
                prev[j - 1] + (0 if r == h else 1),  # substitution
            )
        prev = cur
    return prev[len(hyp)] / len(ref)


# ---------------------------------------------------------------------------
# Retrieval metrics
# ---------------------------------------------------------------------------


def recall_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    """Fraction of relevant ids present in the top-k retrieved ids."""
    if not relevant:
        return 1.0
    hit = len(relevant & set(retrieved[:k]))
    return hit / len(relevant)


def reciprocal_rank(relevant: set[str], retrieved: list[str]) -> float:
    for i, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / i
    return 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[float], p: float) -> float:
    """p-th percentile (linear interpolation), p in [0, 100]."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (p / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


# ---------------------------------------------------------------------------
# Scenario metrics
# ---------------------------------------------------------------------------


def slot_accuracy(expected: dict[str, object], actual: dict[str, object]) -> float:
    """Fraction of expected slots whose confirmed/provisional value matches."""
    if not expected:
        return 1.0
    hits = 0
    for name, want in expected.items():
        got = actual.get(name)
        got_value = getattr(got, "value", got)
        if got_value == want:
            hits += 1
    return hits / len(expected)


def repetition_detected(questions: list[str]) -> bool:
    """True if the agent re-asked an identical question within the call."""
    seen: set[str] = set()
    for q in questions:
        key = normalize_german(q)
        if key in seen:
            return True
        seen.add(key)
    return False
