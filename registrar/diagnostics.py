"""Fixed network classifications shared by Graph transport and Microsoft sign-in."""

import requests


def network_error_kind(error):
    for kind in (
        requests.ConnectTimeout,
        requests.ReadTimeout,
        requests.Timeout,
        requests.exceptions.SSLError,
        requests.exceptions.ProxyError,
        requests.ConnectionError,
    ):
        if isinstance(error, kind):
            return kind.__name__
    return "RequestException"
