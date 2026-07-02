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


class AgentClientError(DomainError):
    message = "Agent client error"


class AgentNetworkError(AgentClientError):
    message = "Agent network error"


class AgentTimeoutError(AgentClientError):
    message = "Agent request timed out"


class AgentHttpError(AgentClientError):
    message = "Agent HTTP error"


class AgentScriptHashMissingError(AgentClientError):
    message = "Agent script hash missing"


class AgentIntegrityMismatchError(AgentClientError):
    message = "Agent integrity or security mismatch"


class AgentRateLimitError(AgentClientError):
    message = "Agent rate limit exceeded"


class AgentServerError(AgentClientError):
    message = "Agent server error"


class OnboardingError(DomainError):
    message = "Onboarding error"


class SshHostKeyMismatchError(OnboardingError):
    message = "SSH host key fingerprint mismatch"


class AgentInstallError(OnboardingError):
    message = "Agent install failed"
