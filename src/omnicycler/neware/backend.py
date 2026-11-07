"""
The OmniCycler backend of a Neware BTS82 cycler.

`NewareBackend` implements `CyclerBackend` on top of the `io/` layer: the
standard features call the base class, and the base class calls the hooks
below. The brand features use the extra methods at the end, which follow the
same per-channel locking and state checks.

The channels are the controller's own: their physical IDs, ratings and current
scales come from the controller (see `io/controller.py`), and the configuration
only overrides channels that differ. The base class reads them once, at startup;
the OmniCycler channel number of unit `u`, channel `c` is `(u - 1) * 8 + c`.

Conversions to BDF units (decision 0002 of omnicycler-features) happen in
`io/records.py` and `io/states.py`; neware8 already reports V, A with positive
current charging, Ah, Wh and s.
"""

import pathlib
import typing
import uuid

import neware8
from aurora_unicycler import CyclingProtocol
from omnicycler.features.backend import ACTIVE_STATES, ENDED_STATES, CyclerBackend, CyclerIdentity
from omnicycler.features.errors import (
    ChannelBusyError,
    ChannelNotClearedError,
    ChannelUnavailableError,
    InvalidSampleError,
    UnsupportedProtocolError,
)
from omnicycler.features.protocol import PLACEHOLDER_SAMPLE_NAME, encode_protocol
from omnicycler.features.types import (
    ChannelInformation,
    ChannelState,
    ChannelStatus,
    DataPoint,
    ProtocolFormat,
    RunInformation,
    Sample,
    StepType,
)

from .config import CHANNELS_PER_UNIT, NewareChannelConfig, NewareConfig
from .io.controller import ConnectionSettings, NewareController
from .io.conversion import compile_step_file, convert_protocol
from .io.errors import NativeProtocolError
from .io.states import channel_status
from .io.store import ProtocolKind, RunEntry
from .types import NativeProtocolSummary, UnitDate, UnitDateKind, UnitInformation

MANUFACTURER = "Neware"

SUPPORTED_STEP_TYPES = (StepType.OPEN_CIRCUIT_VOLTAGE, StepType.CONSTANT_CURRENT, StepType.CONSTANT_VOLTAGE)
"""neware8 compiles CC, CV and CCCV steps and rests; it rejects voltage scans, and impedance is not exported."""

IDENTITY_TIMEOUT = 10.0
"""How long reading the identity waits for a controller to connect, in seconds."""


class NewareBackend(CyclerBackend):
    """A Neware BTS82 cycler behind neware8; see the module documentation."""

    def __init__(
        self,
        settings: ConnectionSettings,
        *,
        model: str,
        simulation: bool,
        discovery_timeout: float = 60.0,
    ) -> None:
        super().__init__()
        self.controller = NewareController(settings)
        self._model = model
        self._initial_simulation = simulation
        self._discovery_timeout = discovery_timeout
        self._addresses: dict[int, neware8.ChannelAddress] = {}  # the served channels, read at startup

    @classmethod
    def from_config(cls, config: NewareConfig) -> typing.Self:
        """Create the backend a connector configuration describes, in its configured mode."""
        settings = ConnectionSettings(
            listen_host=config.listen_host,
            listen_port=config.listen_port,
            controller_host=config.controller_host,
            storage_directory=pathlib.Path(config.storage_directory),
            overrides=tuple(cls.profile_of(channel) for channel in config.channels),
            upload_interval=config.upload_interval,
            start_timeout=config.start_timeout,
            simulation_time_scale=config.simulation_time_scale,
            simulation_status_period=config.simulation_status_period,
            simulation_units=config.simulation_units,
        )
        return cls(
            settings,
            model=config.model,
            simulation=config.simulation_mode,
            discovery_timeout=config.discovery_timeout,
        )

    @property
    def simulation(self) -> bool:
        """Whether the backend talks to the simulated controller."""
        return self.controller.simulation

    @typing.override
    async def open(self) -> None:
        await self.controller.open(simulation=self._initial_simulation)

    @typing.override
    async def close(self) -> None:
        await self.controller.close()

    async def switch_mode(self, *, simulation: bool) -> None:
        """
        Reconnect in simulation or real mode; a failed switch keeps the current mode.

        Raises:
          OSError: If the new mode's listener cannot be opened.
        """
        if simulation == self.simulation:
            return
        await self.controller.close()
        try:
            await self.controller.open(simulation=simulation)
        except BaseException:
            await self.controller.open(simulation=not simulation)
            raise
        self._identity = None  # the other controller has another identity
        self._cleared.clear()  # runs of the other mode are in its own store

    @staticmethod
    def profile_of(channel: NewareChannelConfig) -> neware8.ChannelProfile:
        """The neware8 profile of a configured channel override."""
        return _profile_of(channel)

    def address(self, channel: int) -> neware8.ChannelAddress:
        """The controller address of an OmniCycler channel number."""
        return self._addresses.get(channel) or address_of(channel)

    def profile(self, channel: int) -> neware8.ChannelProfile:
        """
        Return the neware8 profile of an OmniCycler channel number.

        Raises:
          ChannelUnavailableError: If the controller has not reported the channel.
        """
        try:
            return self.controller.profile(self.address(channel))
        except neware8.StateError as error:
            raise ChannelUnavailableError(str(error)) from None

    # Device hooks of CyclerBackend.

    @typing.override
    async def read_identity(self) -> CyclerIdentity:
        await self.controller.wait_ready(IDENTITY_TIMEOUT)
        info = await self.controller.controller_info()
        return CyclerIdentity(
            manufacturer=MANUFACTURER,
            model=self._model,
            serial_number=info.serial_number,
            firmware_version=info.version,
        )

    @typing.override
    async def read_channels(self) -> list[ChannelInformation]:
        timeout = IDENTITY_TIMEOUT if self.simulation else self._discovery_timeout
        try:
            profiles = await self.controller.wait_channels(timeout)
        except neware8.ConnectionLost:
            msg = (
                f"The server does not know the cycler's channels yet: no controller connected within {timeout:g} s. "
                "The first start in real mode needs the controller; check that it is online and configured, or raise "
                "discovery_timeout."
            )
            raise neware8.ConnectionLost(msg) from None
        if not profiles:
            msg = "The controller reported no main channel with usable ratings; configure the channels."
            raise neware8.StateError(msg)
        self._addresses = {channel_number(address): address for address in profiles}
        return [
            ChannelInformation(
                channel=channel_number(address),
                minimal_voltage=0.0,
                maximal_voltage=profile.voltage_rating_v,
                maximal_current=profile.current_rating_a,
                measured_quantities=[],
            )
            for address, profile in sorted(profiles.items())
        ]

    @typing.override
    async def read_supported_step_types(self) -> list[StepType]:
        return list(SUPPORTED_STEP_TYPES)

    @typing.override
    async def read_statuses(self) -> list[ChannelStatus]:
        views = await self.controller.views(self._addresses.values())
        return [
            channel_status(channel_number(address), view.status, view.run, view.record_count)
            for address, view in sorted(views.items())
        ]

    @typing.override
    async def read_run_information(self, channel: int) -> RunInformation:
        run = await self._run(channel)
        return RunInformation(
            run_id=run.run_id,
            sample=Sample(name=run.sample_name, nominal_capacity=run.nominal_capacity),
            protocol_format=ProtocolFormat.AURORA_UNICYCLER
            if run.kind is ProtocolKind.UNICYCLER
            else ProtocolFormat.NATIVE,
            protocol=run.protocol,
            start_time=(run.started_ns or 0) / 1e9,
        )

    @typing.override
    async def read_data(self, channel: int, from_index: int, count: int) -> list[DataPoint]:
        run = await self._run(channel)
        return await self.controller.store.read(run, from_index, count)

    @typing.override
    async def check(self, channel: int, protocol: CyclingProtocol) -> list[str]:
        try:
            return convert_protocol(protocol, self.profile(channel)).warnings
        except NativeProtocolError as error:
            raise UnsupportedProtocolError(str(error)) from None

    @typing.override
    async def start(self, channel: int, protocol: CyclingProtocol, run_id: str) -> None:
        profile = self.profile(channel)
        converted = convert_protocol(protocol, profile)
        entry = RunEntry(
            run_id=run_id,
            unit=profile.address.unit,
            channel=profile.address.channel,
            sample_name=protocol.sample.name,
            nominal_capacity=(protocol.sample.capacity_mAh or 0.0) / 1000,
            kind=ProtocolKind.UNICYCLER,
            protocol=encode_protocol(protocol),
            step_positions=converted.step_positions,
        )
        await self.controller.start(profile.address, converted.recipe, entry)

    @typing.override
    async def pause(self, channel: int) -> None:
        await self.controller.stop(self.address(channel))

    @typing.override
    async def resume(self, channel: int) -> None:
        await self.controller.continue_test(self.address(channel))

    @typing.override
    async def stop(self, channel: int) -> None:
        address = self.address(channel)
        view = await self.controller.view(address)
        if view.status is not None and view.status.state is not neware8.ChannelState.STOPPED:
            await self.controller.stop(address)
        if view.run is not None:
            await self.controller.store.mark_stopped(view.run)
        await self.controller.clear_flag(address)

    @typing.override
    async def clear(self, channel: int) -> None:
        address = self.address(channel)
        view = await self.controller.view(address)
        if view.status is not None and view.status.state is neware8.ChannelState.PROTECTED:
            await self.controller.clear_flag(address)
        if view.run is not None:
            await self.controller.store.delete(view.run)  # dropped from OmniCycler for good

    # Brand operations, used by the Neware features.

    def validate_native_protocol(self, channel: int, protocol: bytes) -> NativeProtocolSummary:
        """
        Compile a BTS Step File for a channel, offline.

        Raises:
          NativeProtocolError: If the step file cannot run on the channel.
        """
        _, compiled = compile_step_file(protocol, self.profile(channel))
        return NativeProtocolSummary(step_count=compiled.step_count, maximal_duration=compiled.maximum_duration_s)

    def validate_sample(self, sample: Sample) -> None:
        """
        Check the sample of a native start.

        Raises:
          InvalidSampleError: If the sample name is a placeholder.
        """
        if sample.name.strip() in {"", PLACEHOLDER_SAMPLE_NAME}:
            msg = f"Sample name {sample.name!r} is a placeholder; give the cell a real name."
            raise InvalidSampleError(msg)

    async def start_native_protocol(self, channel: int, protocol: bytes, sample: Sample) -> None:
        """
        Start a BTS Step File on an idle channel, with the same checks as `start_protocol`.

        Raises:
          ChannelBusyError: If the channel is running or paused a protocol.
          ChannelNotClearedError: If the channel holds an ended run.
          ChannelUnavailableError: If the channel is unavailable.
        """
        profile = self.profile(channel)
        recipe, compiled = compile_step_file(protocol, profile)
        async with self._locks[channel]:
            state = (await self.get_channel_status(channel)).state
            _require_idle(channel, state)
            entry = RunEntry(
                run_id=str(uuid.uuid4()),
                unit=profile.address.unit,
                channel=profile.address.channel,
                sample_name=sample.name,
                nominal_capacity=sample.nominal_capacity,
                kind=ProtocolKind.NATIVE,
                protocol=protocol,
                step_positions={step.step_id: step.index for step in compiled.steps},
            )
            await self.controller.start(profile.address, recipe, entry)
            self._cleared.discard(channel)

    async def get_units(self) -> list[int]:
        """The lower units of the served channels."""
        await self.get_channels()
        return sorted({address.unit for address in self._addresses.values()})

    async def controller_identifier(self) -> str:
        """The controller's GUID, as hexadecimal digits."""
        return (await self.controller.controller_info()).identity.hex()

    async def clock_setting_requested(self) -> bool:
        """Whether the controller asks for its clock to be set."""
        return (await self.controller.controller_info()).clock_setting_requested

    async def unit_information(self, unit: int) -> UnitInformation:
        """The identity, firmware and dates of one lower unit."""
        info = await self.controller.unit_info(unit)
        dates = [
            UnitDate(kind=kind, time=time.astimezone())
            for kind, time in (
                (UnitDateKind.PRODUCTION, info.production_time),
                (UnitDateKind.VALID_UNTIL, info.valid_until),
                (UnitDateKind.LATEST_CALIBRATION, info.latest_calibration),
            )
            if time is not None
        ]
        return UnitInformation(
            unit=unit,
            identifier=info.identity.hex(),
            serial_number=info.serial_number,
            firmware_version=info.version,
            dates=dates,
        )

    async def get_upload_interval(self) -> int:
        """The controller's status upload interval, in seconds."""
        return self.controller.upload_interval

    async def set_upload_interval(self, interval: int) -> None:
        """
        Change the controller's status upload interval.

        Raises:
          SettingRejectedError: If the controller rejects the interval.
        """
        await self.controller.set_upload_interval(interval)

    async def synchronize_clock(self) -> None:
        """
        Set the controller's clock to the host's local time.

        Raises:
          ChannelsNotIdleError: If a channel is not finished or shows an alarm.
          SettingRejectedError: If the controller rejects the time.
        """
        await self.controller.synchronize_clock()

    async def _run(self, channel: int) -> RunEntry:
        view = await self.controller.view(self.address(channel))
        if view.run is None:
            msg = f"Channel {channel} holds no run of this server."
            raise neware8.StateError(msg)
        return view.run


def channel_number(address: neware8.ChannelAddress) -> int:
    """The OmniCycler channel number of a controller address."""
    return (address.unit - 1) * CHANNELS_PER_UNIT + address.channel


def address_of(channel: int) -> neware8.ChannelAddress:
    """The controller address of an OmniCycler channel number."""
    unit, index = divmod(channel - 1, CHANNELS_PER_UNIT)
    return neware8.ChannelAddress(unit + 1, index + 1)


def _profile_of(channel: NewareChannelConfig) -> neware8.ChannelProfile:
    return neware8.ChannelProfile(
        address=neware8.ChannelAddress(channel.unit, channel.channel),
        physical_id=channel.physical_id,
        voltage_rating_v=channel.voltage_rating,
        current_rating_a=channel.current_rating,
        current_scale=channel.current_scale,
        charge_range_raw=channel.charge_range_raw,
    )


def _require_idle(channel: int, state: ChannelState) -> None:
    name = state.name.lower()
    if state in ACTIVE_STATES:
        msg = f"Channel {channel} is {name}; stop its protocol first."
        raise ChannelBusyError(msg)
    if state in ENDED_STATES:
        msg = f"Channel {channel} holds a {name} run; clear the channel first."
        raise ChannelNotClearedError(msg)
    if state is ChannelState.UNAVAILABLE:
        msg = f"Channel {channel} is unavailable."
        raise ChannelUnavailableError(msg)


__all__ = ["MANUFACTURER", "SUPPORTED_STEP_TYPES", "NewareBackend"]
