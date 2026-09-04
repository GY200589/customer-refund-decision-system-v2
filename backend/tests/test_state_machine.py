import pytest

from app.domain.state_machine import (
    CaseStatus,
    InvalidTransition,
    assert_transition,
    can_transition,
    TERMINAL_STATUSES,
)


def test_valid_transitions():
    assert can_transition("CREATED", "RUNNING")
    assert can_transition("RUNNING", "SUSPENDED")
    assert can_transition("RUNNING", "APPROVED")
    assert can_transition("RUNNING", "COMPLETED")
    assert can_transition("SUSPENDED", "APPROVED")
    assert can_transition("APPROVED", "COMPLETED")


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        assert_transition("COMPLETED", "APPROVED")
    with pytest.raises(InvalidTransition):
        assert_transition("SUSPENDED", "RUNNING")
    with pytest.raises(InvalidTransition):
        assert_transition("APPROVED", "SUSPENDED")


def test_terminal_has_no_exit():
    for status in TERMINAL_STATUSES:
        assert not can_transition(status.value, "RUNNING")
        assert not can_transition(status.value, "APPROVED")
