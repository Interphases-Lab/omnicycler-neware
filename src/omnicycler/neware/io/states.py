"""
Neware channel states as OmniCycler channel states.

The BTS82 has no pause command: its Stop keeps a test resumable with Continue,
and Clear Flag turns a stopped test finished. This server therefore pauses with
Stop, resumes with Continue, and stops with Stop followed by Clear Flag, and
remembers in its run store that a client stopped the run. The mapping:

| Native state | Run started by this server | Otherwise |
| --- | --- | --- |
| finish | `FINISHED`, `STOPPED` if a client stopped it, `FAULTED` with an alarm | `IDLE` |
| running, wait start, wait timeout, synchronous control | `RUNNING` | `UNAVAILABLE` |
| stop, pause, offline pause, beep, reserved pause | `PAUSED` | `UNAVAILABLE` |
| protect, finish protect, fixture states, unknown | `FAULTED` | `UNAVAILABLE` |
| not reported, stale or disconnected | `UNAVAILABLE`, still naming the run | `UNAVAILABLE` |

A channel names its run in `RunId` whenever this server started the test the
controller last reported on it; while the controller is disconnected, that run
stays readable. A run that a client cleared is deleted from the store, so its
channel reports `IDLE` without a run. Tests started outside this server, for
example in the BTS software, are `UNAVAILABLE`: their history is not kept, so
this server cannot describe them as runs.
"""

import dataclasses
import math

import neware8
from neware8 import ChannelState as Native
from omnicycler.features.types import ChannelState, ChannelStatus

from .store import RunEntry

RUNNING_STATES = frozenset({Native.RUNNING, Native.WAIT_START, Native.WAIT_TIMEOUT, Native.SYNCHRONOUS_CONTROL})
PAUSED_STATES = frozenset({Native.STOPPED, Native.PAUSED, Native.OFFLINE_PAUSED, Native.BEEP, Native.RESERVED_PAUSE})


def channel_status(
    number: int,
    status: neware8.ChannelStatus | None,
    run: RunEntry | None,
    record_count: int,
) -> ChannelStatus:
    """
    Describe one channel in OmniCycler terms.

    Args:
      number: The OmniCycler channel number.
      status: The channel's latest fresh status, or `None`.
      run: This server's run of the test the controller last reported, if this server started it.
      record_count: The number of stored records of that run.
    """
    if status is None:
        return _unreported(number, run, record_count)
    current = math.nan if status.current_a is None else status.current_a
    if run is None:
        state = ChannelState.IDLE if status.state is Native.FINISHED else ChannelState.UNAVAILABLE
        return _without_run(number, state, status.voltage_v, current)

    state = run_state(status, run)
    return ChannelStatus(
        channel=number,
        state=state,
        run_id=run.run_id,
        voltage=status.voltage_v,
        current=current,
        test_time=status.elapsed_s,
        cycle_count=status.cycle,
        protocol_step=run.step_positions.get(status.step_id, status.step_id),
        record_count=record_count,
        fault_reason=fault_reason(status) if state is ChannelState.FAULTED else "",
    )


def run_state(status: neware8.ChannelStatus, run: RunEntry) -> ChannelState:
    """Return the OmniCycler state of a run this server started."""
    native = status.state
    if native is Native.FINISHED:
        if run.stopped:
            return ChannelState.STOPPED
        return ChannelState.FAULTED if status.alarm_code else ChannelState.FINISHED
    if native in RUNNING_STATES:
        return ChannelState.RUNNING
    if native in PAUSED_STATES:
        return ChannelState.PAUSED
    return ChannelState.FAULTED


def fault_reason(status: neware8.ChannelStatus) -> str:
    """The cycler's reason for a fault, in words, with its alarm code."""
    if status.alarm_code:
        info = neware8.alarm_info(status.alarm_code)
        return f"{info.message} (Neware alarm {status.alarm_code})"
    return f"The cycler reports the channel state {status.state.value!r}."


def _unreported(number: int, run: RunEntry | None, record_count: int) -> ChannelStatus:
    if run is None:
        return _without_run(number, ChannelState.UNAVAILABLE, math.nan, math.nan)
    return dataclasses.replace(
        _without_run(number, ChannelState.UNAVAILABLE, math.nan, math.nan), run_id=run.run_id, record_count=record_count
    )


def _without_run(number: int, state: ChannelState, voltage: float, current: float) -> ChannelStatus:
    return ChannelStatus(
        channel=number,
        state=state,
        run_id="",
        voltage=voltage,
        current=current,
        test_time=0.0,
        cycle_count=0,
        protocol_step=0,
        record_count=0,
    )


__all__ = ["PAUSED_STATES", "RUNNING_STATES", "channel_status", "fault_reason", "run_state"]
