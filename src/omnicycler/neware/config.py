import collections
import dataclasses
import importlib.metadata
import ipaddress
import typing

from unitelabs.cdk import ConfigurationError, ConnectorBaseConfig, Field, SiLAServerConfig, validate_config

CHANNELS_PER_UNIT = 8
"""Main channels per BTS82 lower unit; OmniCycler channel numbers count across units."""


def _sila_server() -> SiLAServerConfig:
    return SiLAServerConfig(
        name="OmniCycler Neware",
        type="BatteryCycler",
        description="A Neware BTS82 battery cycler, implementing the OmniCycler standard features.",
        version=importlib.metadata.version("omnicycler-neware"),
        vendor_url="https://github.com/Interphases-Lab/omnicycler-neware",
    )


@dataclasses.dataclass
class NewareChannelConfig:
    """
    A main channel whose channel map or ratings differ from what the controller advertises.

    The server takes every channel's physical ID, ratings and current scale from the controller; list a channel
    here only if the installation's channel map was changed in the manufacturer software, or its ratings are not
    the advertised ones. Every value is then taken from here. The OmniCycler channel number is
    `(unit - 1) * 8 + channel`.
    """

    unit: typing.Annotated[int, Field(ge=1, le=32)]
    """The lower unit, as the controller numbers it."""

    channel: typing.Annotated[int, Field(ge=1, le=CHANNELS_PER_UNIT)]
    """The channel within the unit."""

    physical_id: typing.Annotated[int, Field(ge=0, le=255)]
    """The controller-wide physical channel ID of the installation's channel map. Must be unique."""

    voltage_rating: typing.Annotated[float, Field(gt=0)]
    """The rated voltage of the channel, in volt."""

    current_rating: typing.Annotated[float, Field(gt=0)]
    """The rated current of the channel, in ampere."""

    current_scale: typing.Annotated[int, Field(ge=1)]
    """The native current scale of the channel's range: native current units per milliampere."""

    charge_range_raw: int | None = None
    """The native charge-range encoding, needed only if records report a zero current range."""

    @property
    def number(self) -> int:
        """The OmniCycler channel number."""
        return (self.unit - 1) * CHANNELS_PER_UNIT + self.channel


@dataclasses.dataclass
class NewareConfig(ConnectorBaseConfig):
    """Configuration of the OmniCycler Neware server."""

    sila_server: SiLAServerConfig = dataclasses.field(default_factory=_sila_server)

    simulation_mode: bool = True
    """Whether the server starts with a simulated BTS82 controller instead of the real one."""

    listen_host: str = "0.0.0.0"  # noqa: S104  # the controller connects to this host
    """The local IP address the controller connects to, as configured on the controller."""

    listen_port: typing.Annotated[int, Field(ge=1, le=65535)] = 8001
    """The local TCP port the controller connects to, as configured on the controller."""

    controller_host: str = "127.0.0.1"
    """The controller's IP address; connections from any other address are refused."""

    storage_directory: str = "neware-data"
    """Where the server keeps runs and their history. Simulation mode uses its own `simulation` subdirectory."""

    channels: list[NewareChannelConfig] = dataclasses.field(default_factory=list)
    """Channels whose channel map or ratings differ from what the controller advertises; usually none."""

    discovery_timeout: typing.Annotated[float, Field(ge=0)] = 60.0
    """
    How long the first start in real mode waits for the controller to report its channels, in seconds.

    The server remembers the channels of every controller connection, so later starts do not wait. A first start
    without the controller fails.
    """

    model: str = "BTS82"
    """The cycler model reported by `CyclerInformationProvider.Model`."""

    upload_interval: typing.Annotated[int, Field(ge=1, le=255)] = 5
    """The controller's status upload interval in seconds, as currently set on the controller."""

    start_timeout: typing.Annotated[float, Field(gt=0)] = 30.0
    """How long a start waits for the controller to report the new test, in seconds."""

    status_interval: typing.Annotated[float, Field(gt=0)] = 1.0
    """How often channel statuses are polled for subscribers and monitors, in seconds."""

    simulation_time_scale: typing.Annotated[float, Field(gt=0)] = 60.0
    """How many times faster than wall-clock time the simulated cells run."""

    simulation_status_period: typing.Annotated[float, Field(gt=0)] = 0.5
    """Seconds between status uploads of the simulated controller."""

    simulation_units: typing.Annotated[int, Field(ge=1, le=32)] = 1
    """
    The lower units of eight channels the simulated controller has until the real controller was seen.

    Once the server knows the real controller's channels, the simulated controller has the same units.
    """

    @validate_config()
    def _check(self) -> typing.Self:
        for name in ("listen_host", "controller_host"):
            try:
                ipaddress.ip_address(getattr(self, name))
            except ValueError:
                msg = f"{name} must be an IP address, not {getattr(self, name)!r}."
                raise ConfigurationError(msg) from None
        _require_unique("channel", [(channel.unit, channel.channel) for channel in self.channels])
        _require_unique("physical_id", [channel.physical_id for channel in self.channels])
        return self


def _require_unique(label: str, values: list[typing.Any]) -> None:
    duplicates = sorted({value for value, count in collections.Counter(values).items() if count > 1})
    if duplicates:
        msg = f"Every configured {label} must be unique; repeated: {duplicates}."
        raise ConfigurationError(msg)


__all__ = ["CHANNELS_PER_UNIT", "NewareChannelConfig", "NewareConfig"]
