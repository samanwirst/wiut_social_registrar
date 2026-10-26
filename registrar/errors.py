class GraphError(RuntimeError):
    """A safe, user-facing Microsoft Graph error."""

    def __init__(self, message="", *, status_code=None, network_error="", service="graph"):
        super().__init__(message)
        self.status_code = (
            status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        )
        self.network_error = (
            network_error
            if network_error
            in {
                "ConnectTimeout",
                "ReadTimeout",
                "Timeout",
                "SSLError",
                "ProxyError",
                "ConnectionError",
                "RequestException",
            }
            else ""
        )
        self.service = "Microsoft sign-in" if service == "sign-in" else "Microsoft Graph"

    @property
    def diagnostic(self):
        """Operational metadata only; never include exception text or server response bodies."""
        kind = type(self).__name__
        if self.network_error:
            return f"{kind}: {self.service} {self.network_error}"
        if self.status_code is not None:
            return f"{kind}: HTTP {self.status_code}"
        return kind


class AuthenticationError(GraphError):
    pass


class SendStatusUnknown(GraphError):
    """The connection failed after submission may have started. Do not retry."""
