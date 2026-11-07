"""Real mode: channels come from the controller and are remembered for starts without it."""

import asyncio
import socket

import neware8
import pytest
from neware8.simulator import SimulatedController
from omnicycler.features.client import OmniCyclerClient
from omnicycler.features.errors import ChannelUnavailableError
from omnicycler.features.testing import sample_for, short_protocol
from omnicycler.features.testing.plugin import _running
from omnicycler.features.types import ChannelState
from sila.client import ClientConfig

from omnicycler.neware import NewareChannelConfig, NewareConfig, create_app
from omnicycler.neware.backend import NewareBackend


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def real_mode(tmp_path, **values) -> NewareConfig:
    values.setdefault("simulation_mode", False)
    return NewareConfig(
        listen_host="127.0.0.1",
        listen_port=free_port(),
        controller_host="127.0.0.1",
        storage_directory=str(tmp_path),
        status_interval=0.1,
        **values,
    )


async def learn(config: NewareConfig, *, units: int) -> list:
    """Connect a simulated controller in real mode once, and return the channels the server read."""
    backend = NewareBackend.from_config(config)
    async with backend, SimulatedController(port=config.listen_port, units=units, status_period_s=0.05):
        return await backend.read_channels()


async def test_channels_come_from_the_controller_and_overrides_replace_them(tmp_path):
    override = NewareChannelConfig(
        unit=2, channel=3, physical_id=200, voltage_rating=4.2, current_rating=0.005, current_scale=10000
    )
    channels = await learn(real_mode(tmp_path, channels=[override]), units=2)
    assert [channel.channel for channel in channels] == list(range(1, 17))
    assert {(channel.maximal_voltage, channel.maximal_current) for channel in channels if channel.channel != 11} == {
        (5.0, 0.01)
    }
    assert (channels[10].maximal_voltage, channels[10].maximal_current) == (4.2, 0.005)


async def test_a_first_start_without_the_controller_fails_clearly(tmp_path):
    backend = NewareBackend.from_config(real_mode(tmp_path, discovery_timeout=0.2))
    async with backend:
        with pytest.raises(neware8.ConnectionLost, match="first start in real mode needs the controller"):
            await backend.read_channels()


async def test_the_simulated_controller_has_the_learned_units(tmp_path):
    await learn(real_mode(tmp_path), units=2)
    config = real_mode(tmp_path, simulation_mode=True)
    backend = NewareBackend.from_config(config)
    async with backend:
        assert [channel.channel for channel in await backend.read_channels()] == list(range(1, 17))


async def test_the_server_serves_learned_channels_without_a_controller(tmp_path):
    config = real_mode(tmp_path)
    await learn(config, units=1)
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
            assert len(snapshot) == 8
            assert {status.state for status in snapshot} == {ChannelState.UNAVAILABLE}
            channel = (await cycler.information.get_channels())[0]
            with pytest.raises(ChannelUnavailableError):
                await cycler.channels.start_protocol(channel.channel, short_protocol(), sample_for(channel))
