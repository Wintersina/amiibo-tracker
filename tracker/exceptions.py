"""Custom exceptions for Google Sheets operations with user-friendly messages."""


class GoogleSheetsError(Exception):
    """Base exception for Google Sheets related errors."""

    def __init__(self, message, user_message=None, is_retryable=False, action_required=None):
        """
        Initialize the exception.

        Args:
            message: Technical error message for logging
            user_message: User-friendly message to display
            is_retryable: Whether the error can be retried
            action_required: Specific action the user needs to take
        """
        super().__init__(message)
        self.user_message = user_message or message
        self.is_retryable = is_retryable
        self.action_required = action_required


class SpreadsheetNotFoundError(GoogleSheetsError):
    """Raised when a spreadsheet cannot be found."""

    def __init__(self, spreadsheet_id=None):
        user_message = (
            "Your spreadsheet could not be found. It may have been deleted or moved. "
            "Please logout and login again to create a new spreadsheet."
        )
        action_required = "logout_required"
        super().__init__(
            f"Spreadsheet not found: {spreadsheet_id}",
            user_message=user_message,
            is_retryable=False,
            action_required=action_required,
        )
        self.spreadsheet_id = spreadsheet_id


class SpreadsheetPermissionError(GoogleSheetsError):
    """Raised when there are permission issues accessing the spreadsheet."""

    def __init__(self, spreadsheet_id=None):
        user_message = (
            "Permission denied. Your authentication may have expired or the spreadsheet "
            "permissions have changed. Please logout and login again to refresh your access."
        )
        action_required = "logout_required"
        super().__init__(
            f"Permission denied for spreadsheet: {spreadsheet_id}",
            user_message=user_message,
            is_retryable=False,
            action_required=action_required,
        )
        self.spreadsheet_id = spreadsheet_id


class ServiceUnavailableError(GoogleSheetsError):
    """Raised when Google Sheets service is temporarily unavailable."""

    def __init__(self, retry_after=None):
        user_message = (
            "Google Sheets is temporarily unavailable. This is usually temporary. "
            "Please try again in a few moments."
        )
        super().__init__(
            "Google Sheets service unavailable (503)",
            user_message=user_message,
            is_retryable=True,
            action_required="retry",
        )
        self.retry_after = retry_after


class RateLimitError(GoogleSheetsError):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after=30):
        user_message = (
            f"Rate limit reached. Please wait {retry_after} seconds before trying again. "
            "This happens when too many requests are made in a short time."
        )
        super().__init__(
            f"Rate limit exceeded (429)",
            user_message=user_message,
            is_retryable=True,
            action_required="wait",
        )
        self.retry_after = retry_after


class QuotaExceededError(GoogleSheetsError):
    """Raised when API quota is exceeded."""

    def __init__(self):
        user_message = (
            "Daily quota for Google Sheets API has been exceeded. "
            "Please try again later or contact support if this persists."
        )
        super().__init__(
            "API quota exceeded",
            user_message=user_message,
            is_retryable=False,
            action_required="wait_24h",
        )


class InvalidCredentialsError(GoogleSheetsError):
    """Raised when credentials are invalid or expired."""

    def __init__(self):
        user_message = (
            "Your login session has expired. Please logout and login again "
            "to continue using the tracker."
        )
        action_required = "logout_required"
        super().__init__(
            "Invalid or expired credentials",
            user_message=user_message,
            is_retryable=False,
            action_required=action_required,
        )


class NetworkError(GoogleSheetsError):
    """Raised when there's a network connectivity issue."""

    def __init__(self):
        user_message = (
            "Unable to connect to Google Sheets. Please check your internet connection "
            "and try again."
        )
        super().__init__(
            "Network connectivity issue",
            user_message=user_message,
            is_retryable=True,
            action_required="retry",
        )
