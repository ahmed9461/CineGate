from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Hashable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: float = 0.0


class SlidingWindowLimiter:
    """Bounded single-process sliding-window limiter.

    This protects abuse/CPU pressure only. It is intentionally not used as a
    durable correctness or billing primitive.
    """

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        max_keys: int = 10_000,
        clock=time.monotonic,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_keys <= 0:
            raise ValueError("max_keys must be positive")

        self.limit = limit
        self.window_seconds = float(window_seconds)
        self.max_keys = max_keys
        self._clock = clock
        self._events: OrderedDict[Hashable, deque[float]] = OrderedDict()

    def check(self, key: Hashable) -> RateLimitDecision:
        now = self._clock()
        cutoff = now - self.window_seconds

        bucket = self._events.get(key)
        if bucket is None:
            self._evict_if_needed(cutoff)
            bucket = deque()
            self._events[key] = bucket
        else:
            self._events.move_to_end(key)

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.limit:
            retry_after = max(0.001, self.window_seconds - (now - bucket[0]))
            return RateLimitDecision(False, retry_after)

        bucket.append(now)
        return RateLimitDecision(True, 0.0)

    @property
    def key_count(self) -> int:
        return len(self._events)

    def _evict_if_needed(self, cutoff: float) -> None:
        # Prefer removing expired least-recently-seen keys.
        expired: list[Hashable] = []
        for key, bucket in self._events.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                expired.append(key)
            else:
                break

        for key in expired:
            self._events.pop(key, None)

        while len(self._events) >= self.max_keys:
            self._events.popitem(last=False)


@dataclass(slots=True)
class AbuseProtection:
    search: SlidingWindowLimiter
    callback: SlidingWindowLimiter
    reward_claim: SlidingWindowLimiter
    notice: SlidingWindowLimiter | None = None

    @classmethod
    def defaults(cls) -> AbuseProtection:
        return cls(
            search=SlidingWindowLimiter(
                limit=8,
                window_seconds=10,
                max_keys=10_000,
            ),
            callback=SlidingWindowLimiter(
                limit=20,
                window_seconds=10,
                max_keys=10_000,
            ),
            reward_claim=SlidingWindowLimiter(
                limit=20,
                window_seconds=30,
                max_keys=20_000,
            ),
            notice=SlidingWindowLimiter(
                limit=1,
                window_seconds=5,
                max_keys=10_000,
            ),
        )
