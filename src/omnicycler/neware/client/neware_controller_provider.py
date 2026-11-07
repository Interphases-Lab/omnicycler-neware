from omnicycler.features.client._base import (
    ErrorMap,
    error_map,
    from_wire,
    list_from_wire,
    ms,
    response,
    translate_errors,
)
from sila.client import FeatureNamespace

from ..identifiers import feature_identifier
from ..types import UnitInformation

FEATURE = feature_identifier("NewareControllerProvider")
ERRORS: ErrorMap = error_map()


class NewareControllerProviderClient:
    """Typed client of `NewareControllerProvider`: the controller and its lower units."""

    def __init__(self, namespace: FeatureNamespace) -> None:
        self._ns = namespace

    async def get_controller_identifier(self, *, timeout: float | None = None) -> str:
        """The controller's GUID, as 32 hexadecimal digits."""
        with translate_errors(ERRORS):
            return from_wire(str, await self._ns.ControllerIdentifier.read(timeout=ms(timeout)))

    async def get_clock_setting_requested(self, *, timeout: float | None = None) -> bool:
        """Whether the controller asks for its clock to be set."""
        with translate_errors(ERRORS):
            return from_wire(bool, await self._ns.ClockSettingRequested.read(timeout=ms(timeout)))

    async def get_units(self, *, timeout: float | None = None) -> list[int]:
        """The numbers of the cycler's lower units."""
        with translate_errors(ERRORS):
            return list_from_wire(int, await self._ns.Units.read(timeout=ms(timeout)))

    async def get_unit_information(self, unit: int, *, timeout: float | None = None) -> UnitInformation:
        """
        Get the identity, firmware version and dates of one lower unit.

        Raises:
          InvalidParameterError: If the unit does not exist.
        """
        with translate_errors(ERRORS):
            responses = await self._ns.GetUnitInformation(Unit=unit, timeout=ms(timeout))
        return from_wire(UnitInformation, response(responses, "UnitInformation"))


__all__ = ["ERRORS", "FEATURE", "NewareControllerProviderClient"]
