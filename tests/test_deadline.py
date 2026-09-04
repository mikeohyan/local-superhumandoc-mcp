from superhumandoc_mcp.deadline import Deadline


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_the_working_budget_excludes_the_reserved_tail() -> None:
    """Ten of the ninety seconds belong to the terminal fetch of a result the
    user already waited for."""
    d = Deadline(total_s=90.0, reserved_tail_s=10.0, clock=FakeClock())
    assert d.remaining() == 80.0
    assert d.remaining_with_tail() == 90.0


def test_time_spent_comes_off_both_budgets() -> None:
    clock = FakeClock()
    d = Deadline(total_s=90.0, reserved_tail_s=10.0, clock=clock)
    clock.advance(30.0)
    assert d.remaining() == 50.0
    assert d.remaining_with_tail() == 60.0


def test_a_sleep_that_would_outlast_the_budget_is_refused() -> None:
    """Sleeping a truncated interval and trying anyway spends what is left on
    an attempt that cannot finish."""
    clock = FakeClock()
    d = Deadline(total_s=90.0, reserved_tail_s=10.0, clock=clock)
    clock.advance(75.0)
    assert d.remaining() == 5.0
    assert d.can_afford(4.0) is True
    assert d.can_afford(6.0) is False


def test_the_working_budget_expires_before_the_tail_does() -> None:
    clock = FakeClock()
    d = Deadline(total_s=90.0, reserved_tail_s=10.0, clock=clock)
    clock.advance(85.0)
    assert d.expired is True
    assert d.remaining() == 0.0
    assert d.remaining_with_tail() == 5.0
