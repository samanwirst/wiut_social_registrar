"""HTTP/TLS lifecycle only; answer expiration runs independently of the web server."""

import errno
import logging
import ssl

from aiohttp import web

from app.services.qr_designer import QrDesigner
from registrar.config import ConfigurationError

from .application import create_web_app
from .assets import STATIC

logger = logging.getLogger(__name__)


def mini_app_ssl_context(settings):
    if not settings.mini_app_tls_cert_file and not settings.mini_app_tls_key_file:
        return None
    if not settings.mini_app_tls_cert_file or not settings.mini_app_tls_key_file:
        raise ConfigurationError("Direct TLS requires both a certificate and a private key.")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        # An empty password prevents an encrypted key from opening an interactive prompt.
        context.load_cert_chain(
            settings.mini_app_tls_cert_file, settings.mini_app_tls_key_file, password=""
        )
    except (OSError, ValueError):
        raise ConfigurationError(
            "Could not load Mini App TLS files. Check the certificate, matching unencrypted key, and file permissions."
        ) from None
    return context


class MiniAppServer:
    def __init__(self, repository, bot, settings, *, static_dir=STATIC, runtime_health=None):
        self.repository, self.bot, self.settings = repository, bot, settings
        self.static_dir = static_dir
        self.runner = None
        self.runtime_health = runtime_health

    async def start(self):
        if not self.settings.mini_app_url:
            return
        if not (self.static_dir / "index.html").is_file():
            raise ConfigurationError(
                "Mini App frontend is not built. Run 'npm ci --prefix frontend', "
                "then 'npm run build --prefix frontend', or use the Docker image."
            )
        if self.runner is not None:
            raise RuntimeError("The Mini App server is already running.")
        ssl_context = mini_app_ssl_context(self.settings)
        # Never log authentication headers or questionnaire answers.
        self.runner = web.AppRunner(
            create_web_app(
                self.repository,
                self.bot,
                static_dir=self.static_dir,
                qr_designer=QrDesigner(self.settings.qr_images, health=self.runtime_health),
                runtime_health=self.runtime_health,
            ),
            access_log=None,
        )
        try:
            await self.runner.setup()
            await web.TCPSite(
                self.runner,
                self.settings.mini_app_host,
                self.settings.mini_app_port,
                ssl_context=ssl_context,
            ).start()
        except BaseException as error:
            await self.close()
            if isinstance(error, OSError) and error.errno == errno.EADDRINUSE:
                raise ConfigurationError(
                    f"Mini App port {self.settings.mini_app_port} is already in use. "
                    "Another bot instance or web server may already be running. "
                    "Stop it before starting this instance, or change MINI_APP_PORT and MINI_APP_URL together."
                ) from None
            raise
        logger.info(
            "Mini App %s server listening on port %s.",
            "HTTPS" if ssl_context else "HTTP",
            self.settings.mini_app_port,
        )

    async def close(self):
        if self.runner is not None:
            runner, self.runner = self.runner, None
            await runner.cleanup()
