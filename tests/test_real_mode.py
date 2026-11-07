"""Real mode without a controller: the server starts, listens and reports every channel unavailable."""

import asyncio
import socket

import pytest
from omnicycler.features.client import OmniCyclerClient
from omnicycler.features.errors import ChannelUnavailableError
from omnicycler.features.testing import sample_for, short_protocol
from omnicycler.features.testing.plugin import _running
from omnicycler.features.types import ChannelState
from sila.client import ClientConfig

from omnicycler.neware import NewareConfig, create_app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_server_starts_without_a_controller(tmp_path):
    config = NewareConfig(
        simulation_mode=False,
        listen_host="127.0.0.1",
        listen_port=free_port(),
        storage_directory=str(tmp_path),
        status_interval=0.1,
    )
    port = free_port()
    config.sila_server.hostname, config.sila_server.port, config.sila_server.tls = "127.0.0.1", port, False
    config.discovery = None
    config.cloud_servers.enabled = False

    async with asyncio.timeout(60), _running(create_app, config):
        client_config = ClientConfig(hostname="127.0.0.1", port=port, tls=False, default_timeout=30_000)
        async with OmniCyclerClient.connect(client_config, timeout=30) as cycler:
            with socket.create_connection(("127.0.0.1", config.listen_port)):
                pass  # the controller's listener is open
            async with cycler.channels.subscribe_channel_statuses() as statuses:
                snapshot = await anext(statuses)
            assert {status.state for status in snapshot} == {ChannelState.UNAVAILABLE}
            channel = (await cycler.information.get_channels())[0]
            with pytest.raises(ChannelUnavailableError):
                await cycler.channels.start_protocol(channel.channel, short_protocol(), sample_for(channel))
