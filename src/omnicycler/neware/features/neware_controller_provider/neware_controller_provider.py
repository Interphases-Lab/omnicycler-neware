import typing

from unitelabs.cdk import sila

from ...backend import NewareBackend
from ...identifiers import CATEGORY, ORIGINATOR
from ...types import UnitInformation

UnitNumber = typing.Annotated[int, sila.constraints.MinimalInclusive(1), sila.constraints.MaximalInclusive(32)]
"""A lower unit number. Narrowed to the cycler's units at startup."""


class NewareControllerProvider(sila.Feature):
    """
    Describe the Neware BTS82 controller and its lower units.

    The controller's serial number and firmware version are in `CyclerInformationProvider`; this feature adds the
    controller's identifier and clock status and the identity, firmware and calibration dates of each lower unit.
    `Units` lists the unit numbers `GetUnitInformation` accepts. Every value is read from the controller when
    requested, so reading fails while no controller is connected.
    """

    def __init__(self, backend: NewareBackend) -> None:
        super().__init__(originator=ORIGINATOR, category=CATEGORY)
        self.backend = backend

    @typing.override
    async def on_before_start(self) -> None:
        self.add_constraint(self.get_unit_information, "unit", [sila.constraints.Set(self.backend.units)])

    @sila.UnobservableProperty()
    async def get_controller_identifier(self) -> str:
        """The controller's GUID, as 32 hexadecimal digits."""
        return await self.backend.controller_identifier()

    @sila.UnobservableProperty()
    async def get_clock_setting_requested(self) -> bool:
        """Whether the controller asks for its clock to be set; see `NewareSettingsService.SynchronizeClock`."""
        return await self.backend.clock_setting_requested()

    @sila.UnobservableProperty()
    async def get_units(self) -> list[int]:
        """The numbers of the cycler's lower units, each holding up to eight channels."""
        return self.backend.units

    @sila.UnobservableCommand()
    async def get_unit_information(self, unit: UnitNumber) -> UnitInformation:
        """
        Get the identity, firmware version and dates of one lower unit.

        Args:
          Unit: The unit number.

        Returns:
          UnitInformation: The unit's identity, firmware version and dates.
        """
        return await self.backend.unit_information(unit)
