import typing

from unitelabs.cdk.features.core.simulation_controller import (
    SimulationControllerBase,
    StartRealModeFailed,
    StartSimulationModeFailed,
)

from ...backend import NewareBackend

# The CDK's abstract base types its endpoints through the `sila` decorators, so ty sees each plain override as
# replacing a decorated attribute. The CDK moves the decorator onto the override at registration; the ignores below
# only silence that typing gap of the UniteLabs base-class pattern.


class SimulationController(SimulationControllerBase):
    """
    Switch between the real Neware controller and a simulated one.

    In simulation mode the server's neware8 client talks to a simulated BTS82 controller over the native protocol,
    with simulated cells on every configured channel and storage in a separate directory. Switching mode reconnects:
    tests on the real controller keep running while the server is in simulation mode, and simulated tests are lost.
    """

    def __init__(self, backend: NewareBackend) -> None:
        super().__init__()
        self.backend = backend

    @typing.override
    async def start_simulation_mode(self) -> None:  # ty: ignore[invalid-attribute-override]
        """
        Set the SiLA Server to run in Simulation Mode, with a simulated controller. Real tests keep running.

        Raises:
          StartSimulationModeFailed: If the simulated controller cannot be started; the server stays in real mode.
        """
        try:
            await self.backend.switch_mode(simulation=True)
        except Exception as error:
            msg = f"The simulated controller could not be started: {error}"
            raise StartSimulationModeFailed(msg) from error

    @typing.override
    async def start_real_mode(self) -> None:  # ty: ignore[invalid-attribute-override]
        """
        Set the SiLA Server to run in Real Mode and listen for the Neware controller. Simulated tests are lost.

        Raises:
          StartRealModeFailed: If the listener for the controller cannot be opened; the server stays in simulation
            mode.
        """
        try:
            await self.backend.switch_mode(simulation=False)
        except OSError as error:
            msg = f"Cannot listen for the Neware controller: {error}"
            raise StartRealModeFailed(msg) from error

    @typing.override
    async def simulation_mode(self) -> bool:  # ty: ignore[invalid-attribute-override]
        """Whether or not the SiLA Server is in Simulation Mode."""
        return self.backend.simulation
