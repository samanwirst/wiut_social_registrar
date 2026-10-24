"""One bounded Bot API submission; no polling, credentials in logs, or unsafe TLS."""

import http.client
import ipaddress
import json
import socket
import ssl


def send_alert(token, chat_id, message, *, address="", test_environment=False):
    connection = http.client.HTTPSConnection(
        "api.telegram.org", timeout=6, context=ssl.create_default_context()
    )
    try:
        if address:
            ipaddress.IPv4Address(address)
            # Override only TCP; SNI and certificate verification keep the hostname.
            connection._create_connection = lambda target, timeout, source_address=None: (
                socket.create_connection((address, target[1]), timeout, source_address)
            )
        suffix = "test/" if test_environment else ""
        connection.request(
            "POST",
            f"/bot{token}/{suffix}sendMessage",
            body=json.dumps(
                {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
            ),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        data = json.loads(response.read(65536))
        return response.status == 200 and data.get("ok") is True
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()
