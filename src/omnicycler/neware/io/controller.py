"""
The Neware controller, in neware8's vocabulary.

`NewareController` owns one neware8 `Client` (the TCP listener the BTS82
controller connects to) and the run store that client delivers history to. In
simulation mode it also runs neware8's simulated controller against its own
listener. Opening it only listens: it never starts, stops or changes a
test, because the controller may reconnect at any time.

Every channel operation is addressed by `ChannelAddress` and checked against the
TestID the controller reports, as neware8 requires.
"""

import asyncio
import dataclasses
import datetime
import logging
import pathlib
import time
import typing

import neware8

from .errors import ChannelsNotIdleError, SettingRejectedError
from .simulation import create_simulator
from .store import NewareStore, RunEntry

if typing.TYPE_CHECKING:
    from neware8.simulator import SimulatedController

logger = logging.getLogger(__name__)

SIMULATION_DIRECTORY = "simulation"
"""The storage subdirectory of simulation mode; a store belongs to one controller."""

READY_TIMEOUT = 10.0
"""How long opening in simulation mode waits for the simulated controller, in seconds."""


@dataclasses.dataclass(frozen=True)
class ConnectionSettings:
    """
    How to reach the controller and keep its data.

    Attributes:
      listen_host: The local IP address the controller connects to.
      listen_port: The local TCP port the controller connects to.
      controller_host: The controller's IP address.
      storage_directory: Where the run store keeps its database.
      profiles: The installed channels.
      upload_interval: The controller's status upload interval, in seconds.
      start_timeout: How long a start waits for the controller to report the new test, in seconds.
      simulation_time_scale: How many times faster than wall-clock time simulated cells run.
      simulation_status_period: Seconds between status uploads of the simulated controller.
    """

    listen_host: str
    listen_port: int
    controller_host: str
    storage_directory: pathlib.Path
    profiles: tuple[neware8.ChannelProfile, ...]
    upload_interval: int
    start_timeout: float
    simulation_time_scale: float
    simulation_status_period: float


@dataclasses.dataclass(frozen=True)
class ChannelView:
    """
    What the controller and this server know about one channel.

    Attributes:
      status: The latest fresh status, or `None` if none is available.
      run: This server's run of the test the status reports, if this server started it.
      record_count: The number of stored records of that run.
    """

    status: neware8.ChannelStatus | None
    run: RunEntry | None
    record_count: int = 0


class NewareController:
    """The BTS82 controller behind a neware8 client, real or simulated."""

    def __init__(self, settings: ConnectionSettings) -> None:
        self.settings = settings
        self.simulation = False
        self._client: neware8.Client | None = None
        self._simulator: SimulatedController | None = None
        self._store: NewareStore | None = None

    @property
    def client(self) -> neware8.Client:
        """The open neware8 client."""
        if self._client is None:
            msg = "The Neware controller connection is closed."
            raise neware8.ConnectionLost(msg)
        return self._client

    @property
    def store(self) -> NewareStore:
        """The run store of the current mode."""
        if self._store is None:
            msg = "The Neware controller connection is closed."
            raise neware8.ConnectionLost(msg)
        return self._store

    @property
    def connected(self) -> bool:
        """Whether a controller is connected and its identity verified."""
        return self._client is not None and self._client.connected

    async def open(self, *, simulation: bool) -> None:
        """
        Listen for the controller, in simulation mode for a simulated one.

        Raises:
          OSError: If the listener cannot be opened, for example because the port is in use.
        """
        settings = self.settings
        directory = settings.storage_directory / SIMULATION_DIRECTORY if simulation else settings.storage_directory
        store = NewareStore(directory)
        await store.open()
        client = neware8.Client(
            host="127.0.0.1" if simulation else settings.listen_host,
            controller_host="127.0.0.1" if simulation else settings.controller_host,
            history=store,
            port=0 if simulation else settings.listen_port,
            profiles=settings.profiles,
            upload_interval_raw=settings.upload_interval,
        )
        try:
            await client.listen()
        except BaseException:
            await client.close()
            await store.close()
            raise
        self._client, self._store = client, store
        self.simulation = simulation
        if simulation:
            units = max(profile.address.unit for profile in settings.profiles)
            self._simulator = create_simulator(
                client.listening_port,
                units=units,
                time_scale=settings.simulation_time_scale,
                status_period=settings.simulation_status_period,
            )
            await self._simulator.start()
            await client.wait_ready(READY_TIMEOUT)
            await self._await_statuses(READY_TIMEOUT)
        logger.info("Listening for the %s controller", "simulated" if simulation else "Neware")

    async def close(self) -> None:
        """Stop listening. Tests on the controller keep running."""
        simulator, client, store = self._simulator, self._client, self._store
        self._simulator = self._client = self._store = None
        if simulator is not None:
            await simulator.close()
        if client is not None:
            await client.close()
        if store is not None:
            await store.close()

    async def wait_ready(self, timeout: float) -> None:
        """
        Wait until a controller is connected and identified.

        Raises:
          ConnectionLost: If no controller is connected within `timeout` seconds.
        """
        try:
            await self.client.wait_ready(timeout)
        except TimeoutError:
            msg = f"No Neware controller connected within {timeout:g} s; check that it is online and configured."
            raise neware8.ConnectionLost(msg) from None

    # Channels and runs.

    async def views(self) -> dict[neware8.ChannelAddress, ChannelView]:
        """Return what is known about every configured channel."""
        client, store = self._client, self._store
        if client is None or store is None or not client.connected:
            return {profile.address: ChannelView(None, None) for profile in self.settings.profiles}
        snapshot = client.snapshot
        found: dict[neware8.ChannelAddress, tuple[neware8.ChannelStatus | None, RunEntry | None]] = {}
        for profile in self.settings.profiles:
            status = snapshot.get(profile.address)
            if status is not None and status.age_s > client.maximum_status_age:
                status = None
            run = store.run_on(profile.address, status.test_id) if status is not None else None
            found[profile.address] = (status, run)
        counts = await store.record_counts([run for _, run in found.values() if run is not None])
        return {
            address: ChannelView(status, run, counts[run.run_id] if run is not None else 0)
            for address, (status, run) in found.items()
        }

    async def view(self, address: neware8.ChannelAddress) -> ChannelView:
        """Return what is known about one channel."""
        return (await self.views())[address]

    async def start(
        self, profile: neware8.ChannelProfile, recipe: neware8.Recipe, entry: RunEntry
    ) -> neware8.ChannelStatus:
        """
        Start a recipe on a finished channel and wait until the controller reports the new test.

        The run is stored after neware8's readiness checks and before the first device write;
        the store learns its TestID in the controller's start acknowledgement.

        Raises:
          StateError: If neware8's readiness checks fail.
          OperationRejected: If the controller rejected the start.
          OperationUncertain: If the start's outcome is unknown; it is never retried.
        """
        client, store = self.client, self.store

        async def attempt() -> None:
            await store.attempt(entry)

        test = await client.start(recipe, profile, on_attempt=attempt)
        # Statuses handled before the start returned may show the armed, not yet running channel.
        return await self._await_test(profile.address, test.test_id, after_ns=time.time_ns())

    async def stop(self, address: neware8.ChannelAddress) -> None:
        """Stop the channel's test; it stays resumable with `continue_test`."""
        await self._control(address, neware8.Control.STOP)

    async def continue_test(self, address: neware8.ChannelAddress) -> None:
        """Continue a stopped or paused test, acknowledging its alarm if it shows one."""
        status = self._status(address)
        alarm = status.alarm_code or None
        await self.client.control(
            address, neware8.Control.CONTINUE, expected_test_id=status.test_id, acknowledged_alarm=alarm
        )

    async def clear_flag(self, address: neware8.ChannelAddress) -> None:
        """Turn a stopped or protected channel finished ("Clear Flag")."""
        await self._control(address, neware8.Control.CLEAR_FLAG)

    # Controller information and settings.

    async def controller_info(self) -> neware8.ControllerInfo:
        """Read the controller's identity and firmware version."""
        return await self.client.controller_info()

    async def unit_info(self, unit: int) -> neware8.UnitInfo:
        """Read a lower unit's identity, firmware version and calibration dates."""
        return await self.client.unit_info(unit)

    @property
    def upload_interval(self) -> int:
        """The controller's status upload interval, in seconds."""
        return self.client.upload_interval_raw

    async def set_upload_interval(self, interval: int) -> None:
        """
        Change the controller's status upload interval.

        Raises:
          SettingRejectedError: If the controller rejects the interval.
        """
        try:
            await self.client.set_upload_interval(interval)
        except neware8.OperationRejected as error:
            msg = f"The controller rejected the upload interval {interval} s: {error}"
            raise SettingRejectedError(msg) from None

    async def synchronize_clock(self) -> None:
        """
        Set the controller's clock to the host's local time.

        Raises:
          ChannelsNotIdleError: If a channel is not finished or shows an alarm.
          SettingRejectedError: If the controller rejects the time.
        """
        now = datetime.datetime.now().replace(tzinfo=None)  # noqa: DTZ005  # the controller clock is local time
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        try:
            await self.client.set_clock(now)
        except neware8.StateError as error:
            msg = f"The controller clock can only be set while every channel is finished and alarm-free: {error}"
            raise ChannelsNotIdleError(msg) from None
        except neware8.OperationRejected as error:
            msg = f"The controller rejected the clock setting: {error}"
            raise SettingRejectedError(msg) from None

    # Helpers.

    def _status(self, address: neware8.ChannelAddress) -> neware8.ChannelStatus:
        status = self.client.snapshot.get(address)
        if status is None:
            msg = f"The controller has not reported channel {address.unit}-{address.channel}."
            raise neware8.StateError(msg)
        return status

    async def _control(self, address: neware8.ChannelAddress, operation: neware8.Control) -> None:
        status = self._status(address)
        await self.client.control(address, operation, expected_test_id=status.test_id)

    async def _await_test(
        self, address: neware8.ChannelAddress, test_id: int, *, after_ns: int
    ) -> neware8.ChannelStatus:
        client = self.client
        try:
            async with asyncio.timeout(self.settings.start_timeout):
                status = await client.wait_status(address, after_ns=after_ns)
                while status.test_id != test_id:
                    status = await client.wait_status(address, after_ns=status.received_at_ns)
        except TimeoutError:
            msg = (
                f"The controller accepted the start but did not report test {test_id} on channel "
                f"{address.unit}-{address.channel} within {self.settings.start_timeout:g} s."
            )
            raise neware8.OperationUncertain(msg) from None
        return status

    async def _await_statuses(self, timeout: float) -> None:
        client = self.client
        expected = {profile.address for profile in self.settings.profiles}
        async with asyncio.timeout(timeout):
            while not expected <= {status.address for status in client.snapshot.channels}:
                await client.wait_snapshot(after_revision=client.snapshot.revision, timeout=timeout)


__all__ = ["SIMULATION_DIRECTORY", "ChannelView", "ConnectionSettings", "NewareController"]
