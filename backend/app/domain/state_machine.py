from enum import Enum


class CaseStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_STATUSES = {CaseStatus.COMPLETED, CaseStatus.REJECTED, CaseStatus.FAILED}


ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.CREATED: {CaseStatus.RUNNING, CaseStatus.FAILED},
    CaseStatus.RUNNING: {
        CaseStatus.SUSPENDED,
        CaseStatus.APPROVED,
        CaseStatus.REJECTED,
        CaseStatus.COMPLETED,
        CaseStatus.FAILED,
    },
    CaseStatus.SUSPENDED: {CaseStatus.APPROVED, CaseStatus.REJECTED, CaseStatus.FAILED},
    CaseStatus.APPROVED: {CaseStatus.COMPLETED, CaseStatus.FAILED},
    CaseStatus.REJECTED: set(),
    CaseStatus.COMPLETED: set(),
    CaseStatus.FAILED: set(),
}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"非法状态流转: {current} -> {target}")


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(CaseStatus(current), set())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
