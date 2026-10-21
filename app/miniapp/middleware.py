import logging

from aiogram.exceptions import TelegramAPIError
from aiohttp import web
from sqlalchemy.exc import SQLAlchemyError

from app.event_errors import EventError

logger = logging.getLogger(__name__)


@web.middleware
async def errors_and_headers(request, handler):
    try:
        response = await handler(request)
    except EventError as error:
        response = web.json_response({"error": str(error)}, status=400)
    except web.HTTPException as error:
        response = web.json_response(
            {"error": error.text if error.status < 500 else "Please try again later."},
            status=error.status,
        )
    except (SQLAlchemyError, TelegramAPIError) as error:
        logger.error("Mini App operation failed (%s).", type(error).__name__)
        response = web.json_response(
            {"error": "The service is temporarily unavailable. Please try again."}, status=503
        )
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' https://telegram.org; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'self' https://telegram.org https://*.telegram.org",
        }
    )
    return response
