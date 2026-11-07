import dataclasses
import math

import neware8
import pytest
from neware8 import ChannelState as Native
from omnicycler.features.types import ChannelState

from omnicycler.neware.io.states import channel_status
from omnicycler.neware.io.store import ProtocolKind, RunEntry

ADDRESS = neware8.ChannelAddress(1, 3)
ENTRY = RunEntry(
    run_id="0b0f4f39-8a0e-4b4e-9b39-5bc3e8f29a11",
    unit=1,
    channel=3,
    sample_name="cell",
    nominal_capacity=0.005,
    kind=ProtocolKind.UNICYCLER,
    protocol=b"{}",
    step_positions={1: 2, 2: 3},
)


def status(state, *, alarm=0, test_id=7, step=2):
    return neware8.ChannelStatus(
        address=ADDRESS,
        test_id=test_id,
        state=state,
        state_raw=0,
        step_type_raw=1,
        step_id=step,
        cycle=4,
        alarm_code=alarm,
        voltage_v=3.7,
        current_a=0.001,
        temperature_c=25.0,
        elapsed_s=120.0,
        step_elapsed_s=10.0,
        received_at_ns=0,
        received_monotonic=0.0,
        raw=b"",
    )


@pytest.mark.parametrize(
    ("native", "expected"),
    [
        (Native.RUNNING, ChannelState.RUNNING),
        (Native.WAIT_START, ChannelState.RUNNING),
        (Native.STOPPED, ChannelState.PAUSED),
        (Native.PAUSED, ChannelState.PAUSED),
        (Native.BEEP, ChannelState.PAUSED),
        (Native.FINISHED, ChannelState.FINISHED),
        (Native.PROTECTED, ChannelState.FAULTED),
        (Native.JAM, ChannelState.FAULTED),
        (Native.UNKNOWN, ChannelState.FAULTED),
    ],
)
def test_states_of_our_runs(native, expected):
    result = channel_status(3, status(native), ENTRY, 12)
    assert result.state is expected
    assert (result.test_time, result.cycle_count, result.protocol_step, result.record_count) == (120.0, 4, 3, 12)
    assert bool(result.fault_reason) is (expected is ChannelState.FAULTED)


def test_a_stopped_run_is_stopped_and_a_finished_run_with_an_alarm_faulted():
    stopped = dataclasses.replace(ENTRY, stopped=True)
    assert channel_status(3, status(Native.FINISHED), stopped, 12).state is ChannelState.STOPPED
    faulted = channel_status(3, status(Native.FINISHED, alarm=733), ENTRY, 12)
    assert faulted.state is ChannelState.FAULTED
    assert "733" in faulted.fault_reason
    assert faulted.fault_reason.startswith(neware8.alarm_info(733).message)


def test_protection_reports_the_alarm_in_words():
    result = channel_status(3, status(Native.PROTECTED, alarm=67), ENTRY, 12)
    assert result.fault_reason == f"{neware8.alarm_info(67).message} (Neware alarm 67)"


def test_channels_without_our_run():
    idle = channel_status(3, status(Native.FINISHED), None, 0)
    assert (idle.state, idle.record_count, idle.voltage) == (ChannelState.IDLE, 0, 3.7)
    assert channel_status(3, status(Native.RUNNING), None, 0).state is ChannelState.UNAVAILABLE
    offline = channel_status(3, None, None, 0)
    assert offline.state is ChannelState.UNAVAILABLE
    assert math.isnan(offline.voltage)
