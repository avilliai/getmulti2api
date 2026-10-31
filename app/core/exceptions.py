"""Custom application exceptions."""

class AppError(Exception):
    """Base application exception."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthenticationError(AppError):
    def __init__(self, message: str = "Invalid or missing API key"):
        super().__init__(message, status_code=401)


class AccountPoolExhaustedError(AppError):
    def __init__(self, message: str = "No available active accounts in the pool"):
        super().__init__(message, status_code=503)


class UpstreamMultiError(AppError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message, status_code=status_code)


class RegistrationError(AppError):
    def __init__(self, message: str):
        super().__init__(message, status_code=400)
