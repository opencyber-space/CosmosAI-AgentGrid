import logging
import time
import requests

# Named logger for the SDK specifically
logger = logging.getLogger("xchange_pysdk")


class XchangeSDKError(Exception):
    """Base exception class for Xchange SDK.

    Captures the error message, underlying HTTP status code, and raw response
    body if available.
    """

    def __init__(self, message, status_code=None, response_body=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class BaseClient:
    """Base HTTP client for Xchange SDK services.

    Handles connection pooling, request retries with exponential backoff, and
    error parsing.
    """

    def __init__(
        self, base_url, max_retries=3, backoff_factor=1.0, timeout=10.0
    ):
        """Initializes the base client.

        Args:
            base_url (str): Base URL of the API gateway / service.
            max_retries (int): Number of retries for transient errors.
            backoff_factor (float): Multiplier for exponential backoff delay.
            timeout (float): Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        self.session = requests.Session()

    def _request(
        self, method, path, max_retries=None, backoff_factor=None, **kwargs
    ):
        """Executes HTTP request with exponential backoff and retry.

        Args:
            method (str): HTTP method (e.g. GET, POST).
            path (str): Endpoint path suffix.
            max_retries (int, optional): Override default max retries.
            backoff_factor (float, optional): Override default backoff factor.
            **kwargs: Extra arguments passed to requests.request.
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        retries = max_retries if max_retries is not None else self.max_retries
        factor = (
            backoff_factor if backoff_factor is not None else self.backoff_factor
        )

        attempt = 0
        while True:
            try:
                logger.info(
                    "Sending %s request to %s (attempt %d/%d)",
                    method,
                    url,
                    attempt + 1,
                    retries + 1,
                )
                logger.debug("Request details: %s", kwargs)

                response = self.session.request(
                    method, url, timeout=self.timeout, **kwargs
                )

                try:
                    response_json = response.json()
                except ValueError:
                    response_json = None

                logger.info(
                    "Received response status %d from %s",
                    response.status_code,
                    url,
                )
                logger.debug("Response content: %s", response.text)

                # Successful HTTP status codes (200, 201)
                if response.status_code in (200, 201):
                    # Check if API response indicates business failure: {"success": false, "message": "..."}
                    if isinstance(response_json, dict) and not response_json.get(
                        "success", True
                    ):
                        raise XchangeSDKError(
                            response_json.get("message", "API business failure"),
                            status_code=response.status_code,
                            response_body=response_json,
                        )
                    return response_json if response_json is not None else response.text

                # Unsuccessful status codes: check if we should retry
                # Client errors 4xx (except 429 Too Many Requests) are permanent - do not retry
                if (
                    400 <= response.status_code < 500
                    and response.status_code != 429
                ):
                    message = "Client Error"
                    if isinstance(response_json, dict):
                        message = response_json.get("message", message)
                    raise XchangeSDKError(
                        message,
                        status_code=response.status_code,
                        response_body=response_json,
                    )

                # Server errors (5xx) or Rate Limiting (429) are transient - raise error to trigger retry
                response.raise_for_status()

            except (requests.RequestException, XchangeSDKError) as e:
                # If it's a permanent business failure or client error exception, do not retry
                if isinstance(e, XchangeSDKError):
                    raise e

                # Determine if we have retries left
                attempt += 1
                if attempt > retries:
                    logger.error(
                        "Max retries exceeded for %s request to %s",
                        method,
                        url,
                    )
                    # Raise final SDK exception
                    if (
                        hasattr(e, "response")
                        and getattr(e, "response") is not None
                    ):
                        status_code = e.response.status_code
                        try:
                            response_json = e.response.json()
                            message = response_json.get(
                                "message", "Server Error"
                            )
                        except Exception:
                            response_json = None
                            message = f"HTTP Error {status_code}"
                        raise XchangeSDKError(
                            message,
                            status_code=status_code,
                            response_body=response_json,
                        )
                    raise XchangeSDKError(
                        f"Request failed after {retries} retries: {str(e)}"
                    )

                # Exponential backoff sleep: factor * (2 ** (attempt - 1))
                sleep_time = factor * (2 ** (attempt - 1))
                logger.warning(
                    "Request to %s failed: %s. Retrying in %.2f seconds...",
                    url,
                    str(e),
                    sleep_time,
                )
                time.sleep(sleep_time)
