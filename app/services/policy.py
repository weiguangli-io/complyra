"""Output policy evaluation for generated answers.

Scans LLM output for sensitive patterns (API keys, passwords, private keys)
and blocks the answer if any pattern matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import settings


@dataclass(frozen=True)
class PolicyEvaluation:
    """Result of evaluating an answer against output policies."""
    blocked: bool
    matched_rules: list[str]
    answer: str


@lru_cache(maxsize=8)
def _compiled_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


def evaluate_output_policy(answer: str) -> PolicyEvaluation:
    from app.core.metrics import POLICY_EVALUATIONS_TOTAL

    if not settings.output_policy_enabled:
        POLICY_EVALUATIONS_TOTAL.labels(result="disabled").inc()
        return PolicyEvaluation(blocked=False, matched_rules=[], answer=answer)

    patterns = tuple(settings.output_policy_block_patterns)
    if not patterns:
        POLICY_EVALUATIONS_TOTAL.labels(result="no_patterns").inc()
        return PolicyEvaluation(blocked=False, matched_rules=[], answer=answer)

    compiled = _compiled_patterns(patterns)
    matched_rules = [pattern for pattern, regex in zip(patterns, compiled) if regex.search(answer)]

    if matched_rules:
        POLICY_EVALUATIONS_TOTAL.labels(result="blocked").inc()
        return PolicyEvaluation(
            blocked=True,
            matched_rules=matched_rules,
            answer=settings.output_policy_block_message,
        )

    POLICY_EVALUATIONS_TOTAL.labels(result="passed").inc()
    return PolicyEvaluation(blocked=False, matched_rules=[], answer=answer)
