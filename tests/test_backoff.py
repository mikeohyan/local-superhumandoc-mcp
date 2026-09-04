from datetime import datetime, timezone

from superhumandoc_mcp.backoff import equal_jitter, parse_retry_after


def test_equal_jitter_halves_the_delay_then_adds_a_random_half() -> None:
    """Shared buckets synchronise unjittered clients into a thundering herd."""
    assert equal_jitter(0, 2.0, 3.0, 60.0, rand=lambda: 0.0) == 1.0
    assert equal_jitter(0, 2.0, 3.0, 60.0, rand=lambda: 1.0) == 2.0
    assert equal_jitter(0, 2.0, 3.0, 60.0, rand=lambda: 0.5) == 1.5


def test_the_delay_grows_by_the_factor() -> None:
    """2 s, 6 s, 18 s, 54 s with the decided base and factor."""
    full = [equal_jitter(n, 2.0, 3.0, 60.0, rand=lambda: 1.0) for n in range(4)]
    assert full == [2.0, 6.0, 18.0, 54.0]


def test_the_delay_is_capped() -> None:
    assert equal_jitter(9, 2.0, 3.0, 60.0, rand=lambda: 1.0) == 60.0


def test_retry_after_reads_integer_seconds() -> None:
    assert parse_retry_after("120") == 120.0


def test_retry_after_reads_an_http_date() -> None:
    now = datetime(2026, 10, 21, 7, 26, 0, tzinfo=timezone.utc)
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT", now=now) == 120.0


def test_an_unparseable_retry_after_is_ignored_rather_than_fatal() -> None:
    """The header is parsed opportunistically and never required."""
    assert parse_retry_after("soon") is None
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None


def test_a_date_in_the_past_is_treated_as_no_wait() -> None:
    now = datetime(2026, 10, 21, 7, 30, 0, tzinfo=timezone.utc)
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT", now=now) == 0.0
