import typing

from unitelabs.cdk import Publisher, Replay, sila

from ...backend import NewareBackend
from ...identifiers import CATEGORY, ORIGINATOR
from ...io.errors import ChannelsNotIdleError, SettingRejectedError
from ...io.units import SECOND

UploadInterval = typing.Annotated[
    int, SECOND, sila.constraints.MinimalInclusive(1), sila.constraints.MaximalInclusive(255)
]


class NewareSettingsService(sila.Feature):
    """
    Change controller-wide settings of the Neware BTS82 controller.

    Settings apply to the whole controller and every channel; they never start, stop or change a test. The upload
    interval sets how often the controller reports channel status; it does not change what a running test records.
    The controller keeps a changed interval, so set the server's `upload_interval` configuration to match it before
    the next server start. Synchronize the clock when `NewareControllerProvider.ClockSettingRequested` is true; it
    needs every channel finished and free of alarms.
    """

    def __init__(self, backend: NewareBackend, *, poll_interval: float = 1.0) -> None:
        super().__init__(originator=ORIGINATOR, category=CATEGORY)
        self.backend = backend
        self._upload_interval = Publisher[int, int](source=backend.get_upload_interval, interval=poll_interval)

    @sila.ObservableProperty()
    async def subscribe_upload_interval(self) -> sila.Stream[UploadInterval]:
        """How often the controller reports the status of its channels."""
        return self._upload_interval.subscribe(replay=Replay.CURRENT)

    @sila.UnobservableCommand(mode=sila.ExecutionMode.QUEUED, errors=[SettingRejectedError])
    async def set_upload_interval(self, interval: UploadInterval) -> None:
        """
        Change how often the controller reports the status of its channels.

        Args:
          Interval: The time between two status reports.
        """
        await self.backend.set_upload_interval(interval)

    @sila.UnobservableCommand(mode=sila.ExecutionMode.QUEUED, errors=[ChannelsNotIdleError, SettingRejectedError])
    async def synchronize_clock(self) -> None:
        """
        Set the controller's clock to the server host's local time, to the millisecond.

        Fails unless every channel is finished and free of alarms.
        """
        await self.backend.synchronize_clock()
