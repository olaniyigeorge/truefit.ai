# TODO Implement exceptions to be used project wide to prevent weird exceptions being thrown
# and to make it easier to handle exceptions in a consistent way across the project.


class DomainError(Exception):
    """Base exception for domain-specific errors."""

    pass


class NotFoundError(DomainError):
    """Raised when a requested resource is not found."""

    pass


class ConflictError(DomainError):
    """Raised when there's a conflict in the requested operation."""

    pass


class PermissionDeniedError(DomainError):
    """Raised when user lacks required permissions."""

    pass
