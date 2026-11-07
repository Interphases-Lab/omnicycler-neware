"""The typed Neware client against the in-process server in simulation mode."""

import asyncio
import dataclasses
import socket

import neware8
import pytest
from omnicycler.features.backend import ENDED_STATES
from omnicycler.features.client import InvalidParameterError
from omnicycler.features.errors import ChannelBusyError, ChannelNotClearedError, ChannelUnavailableError
from omnicycler.features.types import ChannelState, ProtocolFormat, Sample

from omnicycler.neware.io.errors import ChannelsNotIdleError, SettingRejectedError
from omnicycler.neware.types import UnitDateKind

from .step_files import discharge_cycles, long_rest

SAMPLE = Sample(name="native-cell", nominal_capacity=0.005)


# NewareProtocolController


async def test_validate_native_protocol_summarizes_the_program(neware):
    summary = await neware.client.protocols.validate_native_protocol(1, discharge_cycles(), SAMPLE)
    assert summary.step_count == 3
    assert summary.maximal_duration == pytest.approx(30.0)


async def test_native_run_appears_in_the_standard_features(neware):
    client = neware.client
    step_file = discharge_cycles()
    await client.protocols.start_native_protocol(1, step_file, SAMPLE)

    status = await client.channels.wait_for_state(1, ENDED_STATES, timeout=30)
    assert status.state is ChannelState.FINISHED
    run = await client.channels.get_run_information(1)
    assert run.protocol_format is ProtocolFormat.NATIVE
    assert run.protocol == step_file
    assert run.sample == SAMPLE
    points = await client.measurements.get_all_data(1)
    assert [point.record_index for point in points] == list(range(len(points)))
    assert {point.protocol_step for point in points} == {1}
    assert points[-1].cycle_count == 3
    assert points[-1].discharging_capacity == pytest.approx(0.001 * 30 / 3600, rel=1e-3)


async def test_invalid_step_file_and_sample_are_rejected(neware):
    protocols = neware.client.protocols
    with pytest.raises(InvalidParameterError) as error:
        await protocols.start_native_protocol(1, b"<root/>", SAMPLE)
    assert error.value.parameter == "Protocol"
    with pytest.raises(InvalidParameterError) as error:
        await protocols.validate_native_protocol(1, discharge_cycles(), Sample(name="$NAME", nominal_capacity=1.0))
    assert error.value.parameter == "Sample"
    with pytest.raises(InvalidParameterError) as error:
        await protocols.validate_native_protocol(99, discharge_cycles(), SAMPLE)
    assert error.value.parameter == "Channel"


async def test_native_start_on_a_busy_channel_is_rejected(neware):
    protocols = neware.client.protocols
    await protocols.start_native_protocol(1, long_rest(), SAMPLE)
    with pytest.raises(ChannelBusyError):
        await protocols.start_native_protocol(1, long_rest(), SAMPLE)


async def test_native_start_on_an_ended_run_is_rejected_until_cleared(neware):
    client = neware.client
    await client.protocols.start_native_protocol(1, discharge_cycles(), SAMPLE)
    await client.channels.wait_for_state(1, ENDED_STATES, timeout=30)
    with pytest.raises(ChannelNotClearedError):
        await client.protocols.start_native_protocol(1, discharge_cycles(), SAMPLE)
    await client.channels.clear_channel(1)
    await client.protocols.start_native_protocol(1, discharge_cycles(), SAMPLE)


async def test_native_start_without_a_controller_is_rejected(neware):
    await neware.backend.controller._simulator.close()  # the controller goes offline
    async with asyncio.timeout(10):
        while neware.backend.controller.connected:
            await asyncio.sleep(0.05)
    with pytest.raises(ChannelUnavailableError):
        await neware.client.protocols.start_native_protocol(1, discharge_cycles(), SAMPLE)


async def test_native_run_pauses_resumes_and_stops(neware):
    channels = neware.client.channels
    await neware.client.protocols.start_native_protocol(1, long_rest(), SAMPLE)
    await channels.pause_protocol(1)
    await channels.wait_for_state(1, {ChannelState.PAUSED}, timeout=10)
    await channels.resume_protocol(1)
    await channels.wait_for_state(1, {ChannelState.RUNNING}, timeout=10)
    await channels.stop_protocol(1)
    status = await channels.wait_for_state(1, ENDED_STATES, timeout=10)
    assert status.state is ChannelState.STOPPED


# NewareControllerProvider


async def test_controller_identity(neware):
    controller = neware.client.controller
    assert await controller.get_controller_identifier() == bytes(range(16)).hex()
    assert await controller.get_clock_setting_requested() is False
    assert await controller.get_units() == [1]


async def test_unit_information(neware):
    unit = await neware.client.controller.get_unit_information(1)
    assert unit.unit == 1
    assert unit.serial_number == "SIMUNIT00001"
    assert unit.firmware_version == "SIM_UNIT_1"
    assert [date.kind for date in unit.dates] == list(UnitDateKind)
    assert all(date.time.tzinfo is not None for date in unit.dates)
    with pytest.raises(InvalidParameterError) as error:
        await neware.client.controller.get_unit_information(2)
    assert error.value.parameter == "Unit"


# NewareSettingsService


async def test_upload_interval_can_be_changed(neware):
    settings = neware.client.settings
    assert await settings.get_upload_interval(timeout=5) == 5
    async with asyncio.timeout(10), settings.subscribe_upload_interval() as intervals:
        assert await anext(intervals) == 5
        await settings.set_upload_interval(2)
        assert await anext(intervals) == 2
    with pytest.raises(InvalidParameterError) as error:
        await settings.set_upload_interval(0)
    assert error.value.parameter == "Interval"


async def test_rejected_setting_raises(neware, monkeypatch):
    async def rejected(_interval):
        msg = "rejected"
        raise neware8.OperationRejected(msg)

    monkeypatch.setattr(neware.backend.controller.client, "set_upload_interval", rejected)
    with pytest.raises(SettingRejectedError):
        await neware.client.settings.set_upload_interval(3)


async def test_clock_needs_idle_channels(neware):
    await neware.client.settings.synchronize_clock()
    await neware.client.protocols.start_native_protocol(1, long_rest(), SAMPLE)
    with pytest.raises(ChannelsNotIdleError):
        await neware.client.settings.synchronize_clock()


# SimulationController (not wrapped by the typed client)


async def test_failed_switch_to_real_mode_stays_simulated(neware, raw_client):
    simulation = raw_client.feature("org.silastandard/core/SimulationController/v1")
    assert await simulation.SimulationMode.read() is True
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        controller = neware.backend.controller
        controller.settings = dataclasses.replace(controller.settings, listen_port=occupied.getsockname()[1])
        with pytest.raises(Exception, match="Cannot listen"):
            await simulation.StartRealMode()
    assert await simulation.SimulationMode.read() is True
    assert neware.backend.controller.connected
