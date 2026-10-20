from app.handlers import contact_handler, help_handler, lookup_handler, start_handler, verification_handler


def create_routers():
    # Fresh routers allow independent application instances in tests.
    return (start_handler.create_router(), help_handler.create_router(),
            verification_handler.create_router(), contact_handler.create_router(), lookup_handler.create_router())
