import asyncio
import collections.abc
import contextlib

from omnicycler.features.client._base import ErrorMap, error_map, from_wire, ms, translate_errors
from sila.client import FeatureNamespace

from ..identifiers import feature_identifier
from ..io.errors import ChannelsNotIdleError, SettingRejectedError

FEATURE = feature_identifier("NewareSettingsService")
ERRORS: ErrorMap = error_map(ChannelsNotIdleError, SettingRejectedError)


class NewareSettingsServiceClient:
    """Typed client of `NewareSettingsService`: controller-wide settings."""

    def __init__(self, namespace: FeatureNamespace) -> None:
        self._ns = namespace

    @contextlib.asynccontextmanager
    async def subscribe_upload_interval(self) -> collections.abc.AsyncGenerator[collections.abc.AsyncIterator[int]]:
        """Subscribe to the status upload interval in seconds; the subscription closes when the context exits."""
        with translate_errors(ERRORS):
            stream = await self._ns.UploadInterval.subscribe()

        async def values() -> collections.abc.AsyncIterator[int]:
            async for raw in stream:
                yield from_wire(int, raw)

        try:
            yield values()
        finally:
            stream.close()

    async def get_upload_interval(self, *, timeout: float | None = None) -> int:
        """The current status upload interval, in seconds."""
        async with asyncio.timeout(timeout), self.subscribe_upload_interval() as intervals:
            return await anext(intervals)

    async def set_upload_interval(self, interval: int, *, timeout: float | None = None) -> None:
        """
        Change how often the controller reports channel status.

        Args:
          interval: The time between two status reports, in seconds, 1 to 255.
          timeout: The longest to wait for the server, in seconds.

        Raises:
          InvalidParameterError: If the interval is out of range.
          SettingRejectedError: If the controller rejects the interval.
        """
        with translate_errors(ERRORS):
            await self._ns.SetUploadInterval(Interval=interval, timeout=ms(timeout))

    async def synchronize_clock(self, *, timeout: float | None = None) -> None:
        """
        Set the controller's clock to the server host's local time.

        Raises:
          ChannelsNotIdleError: If a channel is not finished or shows an alarm.
          SettingRejectedError: If the controller rejects the time.
        """
        with translate_errors(ERRORS):
            await self._ns.SynchronizeClock(timeout=ms(timeout))


__all__ = ["ERRORS", "FEATURE", "NewareSettingsServiceClient"]
