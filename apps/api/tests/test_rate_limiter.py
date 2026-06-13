"""Tests for the in-memory rate limiter fallback."""
import pytest
from app.api.rate_limiter import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter(max_requests=3, window_seconds=10)


def test_allows_within_limit(limiter):
    for _ in range(3):
        assert limiter._check_memory("test_key") is True


def test_blocks_over_limit(limiter):
    for _ in range(3):
        limiter._check_memory("test_key")
    assert limiter._check_memory("test_key") is False


def test_different_keys_independent(limiter):
    for _ in range(3):
        limiter._check_memory("key_a")
    # key_a is exhausted
    assert limiter._check_memory("key_a") is False
    # key_b should still work
    assert limiter._check_memory("key_b") is True
