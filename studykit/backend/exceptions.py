# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class SessionNotFoundError(Exception):
    pass


class DatabaseError(Exception):
    pass


class StorageError(Exception):
    def __init__(self, operation: str, path: str, cause: Exception | None = None):
        self.operation = operation
        self.path = path
        self.cause = cause
        super().__init__(f"Storage {operation} failed for {path}")


class RateLimitExceeded(Exception):
    def __init__(self, timeout: int = 60, message: str = "Too many requests. Please slow down."):
        self.retry_after = timeout
        super().__init__(message)
