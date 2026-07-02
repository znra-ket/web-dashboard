class DomainError(Exception):
    message = "Domain error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class NotFoundError(DomainError):
    message = "Resource not found"


class ConflictError(DomainError):
    message = "Resource conflict"


class ValidationError(DomainError):
    message = "Validation error"
