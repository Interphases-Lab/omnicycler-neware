"""
Simulation mode: a simulated BTS82 controller on the native protocol.

The server's own neware8 client listens on a local port, and neware8's
`SimulatedController` connects to it like the real device. Every OmniCycler
command therefore goes through the same neware8 client, native frames and
storage as on hardware; only the controller at the far end is simulated.

Like a real BTS82, the simulated controller outlives the server: closing the
server parks it with its channels and tests, and the next open in simulation
mode with the same storage, in the same process, reconnects it. Simulated time
stands still while it is parked.
"""

import asyncio
import pathlib

from neware8.simulator import SimulatedCell, SimulatedController

SIMULATED_CELL_CAPACITY = 0.005
"""The capacity of every simulated cell, in Ah; the conformance kit's samples are 5 mAh at a 10 mA rating."""


def create_simulator(port: int, *, units: int, time_scale: float, status_period: float) -> SimulatedController:
    """
    Create a simulated controller that connects to a local neware8 listener.

    Args:
      port: The listener's port.
      units: The number of lower units to simulate, eight channels each.
      time_scale: How many times faster than wall-clock time the simulated cells run.
      status_period: Wall-clock seconds between status uploads.
    """
    return SimulatedController(
        port=port,
        units=units,
        time_scale=time_scale,
        status_period_s=status_period,
        reconnect_delay_s=0.2,
        cell=lambda _unit, _channel: SimulatedCell(capacity_ah=SIMULATED_CELL_CAPACITY),
    )


_parked: dict[tuple[pathlib.Path, asyncio.AbstractEventLoop], SimulatedController] = {}
"""Simulated controllers whose server was closed, by storage directory and event loop."""


def park_simulator(directory: pathlib.Path, simulator: SimulatedController) -> None:
    """Keep a closed simulated controller, with its channels and tests, for the next open with `directory`."""
    _parked[directory.resolve(), asyncio.get_running_loop()] = simulator


def take_simulator(directory: pathlib.Path) -> SimulatedController | None:
    """Return the simulated controller parked for `directory`, if any, and forget parked ones of closed loops."""
    for key in [key for key in _parked if key[1].is_closed()]:
        del _parked[key]
    return _parked.pop((directory.resolve(), asyncio.get_running_loop()), None)


__all__ = ["SIMULATED_CELL_CAPACITY", "create_simulator", "park_simulator", "take_simulator"]
