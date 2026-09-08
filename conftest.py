import os
import pytest

if "QDRANT_URL" not in os.environ:
    os.environ["QDRANT_URL"] = "http://localhost:8010"


@pytest.fixture(autouse=True)
def stop_background_poller():
    from app.services.poller import stop_poller_daemon
    stop_poller_daemon()
    yield
    stop_poller_daemon()
