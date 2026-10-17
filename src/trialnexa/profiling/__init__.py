"""Descriptive source profiling, independent of standards interpretation."""


class ProfileError(RuntimeError):
    """A structural diagnostic that is safe to log without source cell values."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
