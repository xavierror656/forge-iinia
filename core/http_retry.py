"""Retry helper for the REST clients.

Reuses :class:`core.api_errors.APIError` semantics: only retries when the
exception is marked ``is_retryable`` (5xx + 408/425/429) or it's a transient
``NetworkError``. Backoff is exponential with full jitter to avoid waking
multiple workers in lockstep against a flapping backend.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from core.api_errors import APIError, NetworkError

T = TypeVar("T")
log = logging.getLogger(__name__)


def call_with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> T:
    """Call ``fn`` and retry on transient errors.

    Raises the last exception if every attempt fails. ``base_delay`` and
    ``max_delay`` cap the exponential backoff (full jitter).
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    rand = rng or random
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except APIError as exc:
            if not exc.is_retryable or attempt == attempts:
                raise
            last_exc = exc
        except NetworkError as exc:
            if attempt == attempts:
                raise
            last_exc = exc
        delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
        wait = rand.uniform(0.0, delay)
        log.info(
            "Retrying after %s (attempt %d/%d) in %.2fs",
            type(last_exc).__name__,
            attempt,
            attempts,
            wait,
        )
        sleep(wait)
    assert last_exc is not None
    raise last_exc
