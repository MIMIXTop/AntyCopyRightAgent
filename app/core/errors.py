class ApplicationError(Exception):
    """Base class for expected application failures."""


class ValidationError(ApplicationError):
    """Input or configuration validation failed."""


class UnauthorizedError(ApplicationError):
    """The user must authorize access to Classroom."""


class UpstreamServiceError(ApplicationError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Upstream service returned HTTP {status_code}")


class ExternalServiceUnavailableError(ApplicationError):
    """The upstream service could not be reached in time."""


class InvalidUpstreamResponseError(ApplicationError):
    """The upstream response was not valid JSON or had an invalid shape."""


class ToolNotFoundError(ApplicationError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Unknown tool: {name}")


class ToolArgumentsError(ApplicationError):
    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"Invalid arguments for {name}: {reason}")


class AgentIterationLimitError(ApplicationError):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Agent iteration limit reached: {limit}")