from cinegate.logging import configure_application_logging
from cinegate.web.app import create_app

configure_application_logging()

app = create_app()
