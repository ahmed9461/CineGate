from __future__ import annotations

from cinegate.services.rate_limit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_sliding_window_blocks_until_oldest_event_expires() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(
        limit=2,
        window_seconds=10,
        max_keys=10,
        clock=clock,
    )

    assert limiter.check("user").allowed
    clock.advance(1)
    assert limiter.check("user").allowed

    blocked = limiter.check("user")
    assert not blocked.allowed
    assert 8.9 <= blocked.retry_after <= 9.1

    clock.advance(9.1)
    assert limiter.check("user").allowed


def test_rate_limiter_keys_are_bounded_by_lru_eviction() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(
        limit=1,
        window_seconds=60,
        max_keys=3,
        clock=clock,
    )

    for key in ("a", "b", "c", "d", "e"):
        assert limiter.check(key).allowed

    assert limiter.key_count == 3

    # Oldest keys were evicted rather than growing memory without bound.
    assert limiter.check("a").allowed
    assert limiter.key_count == 3


def test_expired_keys_are_cleaned_before_lru_eviction() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(
        limit=1,
        window_seconds=5,
        max_keys=3,
        clock=clock,
    )

    limiter.check("old-a")
    limiter.check("old-b")
    clock.advance(6)
    limiter.check("fresh")

    assert limiter.key_count == 1


def test_rate_limiter_instances_do_not_share_state() -> None:
    clock = FakeClock()
    first = SlidingWindowLimiter(
        limit=1,
        window_seconds=10,
        clock=clock,
    )
    second = SlidingWindowLimiter(
        limit=1,
        window_seconds=10,
        clock=clock,
    )

    assert first.check(123).allowed
    assert not first.check(123).allowed
    assert second.check(123).allowed
