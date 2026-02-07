import os

import pytest
from httpx import Client


RUN_INTEGRATION = os.getenv("RUN_INTEGRATION") == "1"
BASE_URL = os.getenv("BASE_URL", "http://localhost:10723")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def client(base_url: str):
    with Client(base_url=base_url, timeout=20.0) as c:
        yield c


@pytest.fixture(scope="session")
def integration_enabled() -> bool:
    return RUN_INTEGRATION
