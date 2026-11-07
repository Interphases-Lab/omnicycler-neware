"""
Wire types of the Neware brand features, shared by the features and the typed client.

This module imports only the standard library, `unitelabs.cdk.sila` and
`io/units.py`, so it stays a pure description of the wire. Brand features use
device-native units (decision 0002 of omnicycler-features covers the standard
features only).
"""

import dataclasses
import datetime
import enum
import typing

from unitelabs.cdk import sila

from .io.units import SECOND


class UnitDateKind(enum.Enum):
    """
    Which date of a lower unit a `UnitDate` is.

    Production: When the unit was made.
    ValidUntil: Until when the unit's use is licensed.
    LatestCalibration: When the unit was last calibrated.
    """

    PRODUCTION = enum.auto()
    VALID_UNTIL = enum.auto()
    LATEST_CALIBRATION = enum.auto()


@dataclasses.dataclass
class UnitDate(sila.CustomDataType):
    """
    A date a lower unit reports.

    Attributes:
      Kind: Which date this is.
      Time: The date and time, in the server host's time zone, because the controller clock has none.
    """

    kind: UnitDateKind
    time: datetime.datetime


@dataclasses.dataclass
class UnitInformation(sila.CustomDataType):
    """
    The identity of one lower unit of the cycler.

    Attributes:
      Unit: The unit number, as the controller counts units.
      Identifier: The unit's GUID, as 32 hexadecimal digits.
      SerialNumber: The unit's serial number.
      FirmwareVersion: The unit's firmware version.
      Dates: The dates the unit reports; dates it leaves unset are left out.
    """

    unit: typing.Annotated[int, sila.constraints.MinimalInclusive(1), sila.constraints.MaximalInclusive(32)]
    identifier: str
    serial_number: str
    firmware_version: str
    dates: list[UnitDate]


@dataclasses.dataclass
class NativeProtocolSummary(sila.CustomDataType):
    """
    A Neware step file compiled for a channel.

    Attributes:
      StepCount: The number of native steps, including the final End step.
      MaximalDuration: The longest the program can run, from its step time limits.
    """

    step_count: typing.Annotated[int, sila.constraints.MinimalInclusive(1)]
    maximal_duration: typing.Annotated[float, SECOND, sila.constraints.MinimalInclusive(0.0)]


__all__ = ["NativeProtocolSummary", "UnitDate", "UnitDateKind", "UnitInformation"]
