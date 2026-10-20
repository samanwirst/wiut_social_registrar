from app.handlers import help_handler, lookup_handler, start_handler


def create_routers():
    # Fresh routers allow independent application instances in tests.
    return (start_handler.create_router(), help_handler.create_router(), lookup_handler.create_router())
