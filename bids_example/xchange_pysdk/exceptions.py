class XchangeError(Exception):
    """Base exception for all xchange SDK errors."""
    pass

class XchangeNetworkError(XchangeError):
    """Raised when there is a network-level failure."""
    pass

class XchangeAPIError(XchangeError):
    """
    Raised when the exchange responds but indicates an error state (non-2xx HTTP status),
    or when a response body cannot be interpreted as a JSON object.
    Contains the server's error message extracted from the JSON response if available.
    """
    def __init__(self, message: str, status_code: int = None, payload: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}

class XchangeTimeoutError(XchangeError):
    """
    Raised when a wait budget runs out before a task reaches a terminal state.

    This is not a network failure: every individual poll may have succeeded. It means
    the task was still in flight when the caller's budget expired.
    """
    def __init__(self, message: str, task_id: str = None, last_status: str = None):
        super().__init__(message)
        self.task_id = task_id
        self.last_status = last_status
