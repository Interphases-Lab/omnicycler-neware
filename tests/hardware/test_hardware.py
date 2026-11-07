"""
Read-only checks against a real BTS82 controller. Excluded by default; run them only with explicit approval.

    NEWARE_LISTEN_HOST=192.168.1.10 NEWARE_CONTROLLER_HOST=192.168.1.20 uv run pytest -m hardware tests/hardware

The controller must be configured to connect to NEWARE_LISTEN_HOST on port NEWARE_LISTEN_PORT (default 8001).
These tests only listen, read identity and status, and never start, stop or change a test.
"""

import os
import pathlib

import pytest

from omnicycler.neware import NewareConfig
from omnicycler.neware.backend import NewareBackend

pytestmark = pytest.mark.hardware


@pytest.fixture
def config(tmp_path: pathlib.Path) -> NewareConfig:
    try:
        listen_host, controller_host = os.environ["NEWARE_LISTEN_HOST"], os.environ["NEWARE_CONTROLLER_HOST"]
    except KeyError:
        pytest.skip("Set NEWARE_LISTEN_HOST and NEWARE_CONTROLLER_HOST to run hardware tests.")
    return NewareConfig(
        simulation_mode=False,
        listen_host=listen_host,
        listen_port=int(os.environ.get("NEWARE_LISTEN_PORT", "8001")),
        controller_host=controller_host,
        storage_directory=str(tmp_path),
    )


async def test_controller_reports_identity_channels_and_statuses(config: NewareConfig):
    async with NewareBackend.from_config(config) as backend:
        identity = await backend.get_identity()
        assert identity.manufacturer == "Neware"
        assert identity.serial_number
        channels = await backend.get_channels()  # learned from the controller's metadata
        assert channels
        assert all(channel.maximal_voltage > 0 and channel.maximal_current > 0 for channel in channels)
        statuses = await backend.get_channel_statuses()
        assert len(statuses) == len(channels)
