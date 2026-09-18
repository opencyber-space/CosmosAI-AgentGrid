class OpenarcadeError(Exception):
    """Base exception for all openarcade SDK errors."""
    pass

class OpenarcadeNetworkError(OpenarcadeError):
    """Raised when there is a network-level failure."""
    pass

class OpenarcadeAPIError(OpenarcadeError):
    """
    Raised when the API responds but indicates an error state (non-2xx HTTP status).
    Contains the server's error message extracted from the JSON response if available.
    """
    def __init__(self, message: str, status_code: int = None, payload: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}
