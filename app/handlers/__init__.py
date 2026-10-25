from app.handlers import (
    broadcast_handler,
    contact_handler,
    education_handler,
    event_handler,
    help_handler,
    info_handler,
    panel_handler,
    profile_handler,
    registration_handler,
    start_handler,
    survey_handler,
    verification_handler,
)


def create_routers():
    # Fresh routers allow independent application instances in tests.
    return (
        start_handler.create_router(),
        info_handler.create_router(),
        help_handler.create_router(),
        profile_handler.create_router(),
        verification_handler.create_router(),
        contact_handler.create_router(),
        education_handler.create_router(),
        event_handler.create_router(),
        panel_handler.create_router(),
        broadcast_handler.create_router(),
        survey_handler.create_router(),
        registration_handler.create_router(),
    )
