import httpx


class ApplicationError(Exception):
    """Base class for expected application failures."""


class LLMServiceError(ApplicationError):
    """Ошибка при обращении к провайдеру LLM"""


class ValidationError(ApplicationError):
    """Input or configuration validation failed."""


class UnauthorizedError(ApplicationError):
    """The user must authorize access to Classroom."""


class ForbiddenError(ApplicationError):
    def __init__(self, service: str, detail: str = "") -> None:
        self.service = service
        self.detail = detail
        message = f"{service} permission denied"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class UpstreamServiceError(ApplicationError):
    def __init__(
        self,
        status_code: int,
        service: str = "upstream",
        body: str = "",
    ) -> None:
        self.status_code = status_code
        self.service = service
        self.body = body
        super().__init__(f"{service} returned HTTP {status_code}")


class ExternalServiceUnavailableError(ApplicationError):
    """The upstream service could not be reached in time."""


class InvalidUpstreamResponseError(ApplicationError):
    def __init__(self, service: str = "upstream") -> None:
        self.service = service
        super().__init__(f"{service} returned an invalid response")


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


def safe_error_detail(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        detail = error.get("detail", [])
        reason = detail[0].get("reason", "") if detail else None

        return reason or error.get("message", "")
    except (TypeError, ValueError, AttributeError, IndexError):
        return ""