class VariantNotFoundError(Exception):
    pass


class ConstraintViolationError(Exception):
    """Raised when approving a variant whose constraint_violations is non-empty."""

    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


class InvalidTransitionError(Exception):
    """Raised on any review-state-machine move that isn't legal from the
    variant's current status (e.g. rejecting an already-published variant)."""

    def __init__(self, current_status: str, attempted: str):
        self.current_status = current_status
        self.attempted = attempted
        super().__init__(f"cannot move variant from '{current_status}' to '{attempted}'")


class VariantNotApprovedError(Exception):
    """Raised when scheduling is attempted on a variant that isn't 'approved'."""

    def __init__(self, current_status: str):
        self.current_status = current_status
        super().__init__(
            f"variant must be 'approved' to schedule; it is '{current_status}'"
        )
