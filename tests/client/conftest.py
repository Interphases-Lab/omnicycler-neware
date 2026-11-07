import dataclasses
import socket

import pytest
import pytest_asyncio
from omnicycler.features.testing.plugin import _running
from sila.client import Client, ClientConfig

import omnicycler.neware
from omnicycler.neware.backend import NewareBackend
from omnicycler.neware.client import NewareClient


@dataclasses.dataclass
class Server:
    config: ClientConfig
    backend: NewareBackend
    client: NewareClient


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture
async def neware(omnicycler_config, monkeypatch):
    """The server in simulation mode with its backend, and a connected `NewareClient`."""
    created: list[NewareBackend] = []

    class RecordedBackend(NewareBackend):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(omnicycler.neware, "NewareBackend", RecordedBackend)
    port = free_port()
    omnicycler_config.sila_server.hostname = "127.0.0.1"
    omnicycler_config.sila_server.port = port
    omnicycler_config.sila_server.tls = False
    omnicycler_config.discovery = None
    omnicycler_config.cloud_servers.enabled = False
    async with _running(omnicycler.neware.create_app, omnicycler_config):
        config = ClientConfig(hostname="127.0.0.1", port=port, tls=False, default_timeout=30_000)
        async with NewareClient.connect(config, timeout=30) as client:
            yield Server(config, created[0], client)


@pytest_asyncio.fixture
async def raw_client(neware):
    """An untyped `sila.client` connection, for features the typed client does not wrap."""
    client = Client(neware.config)
    await client.open()
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
def omnicycler_config(omnicycler_config):
    omnicycler_config.listen_host = "127.0.0.1"
    return omnicycler_config
