class GraphError(RuntimeError):
    """A safe, user-facing Microsoft Graph error."""


class AuthenticationError(GraphError):
    pass


class SendStatusUnknown(GraphError):
    """The connection failed after submission may have started. Do not retry."""
