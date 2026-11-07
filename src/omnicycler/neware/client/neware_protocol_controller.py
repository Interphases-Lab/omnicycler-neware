from omnicycler.features.client._base import ErrorMap, error_map, from_wire, ms, response, to_wire, translate_errors
from omnicycler.features.errors import ChannelBusyError, ChannelNotClearedError, ChannelUnavailableError
from omnicycler.features.types import Sample
from sila.client import FeatureNamespace

from ..identifiers import feature_identifier
from ..types import NativeProtocolSummary

FEATURE = feature_identifier("NewareProtocolController")
ERRORS: ErrorMap = error_map(ChannelBusyError, ChannelNotClearedError, ChannelUnavailableError)


class NewareProtocolControllerClient:
    """Typed client of `NewareProtocolController`: run native Neware step files."""

    def __init__(self, namespace: FeatureNamespace) -> None:
        self._ns = namespace

    async def start_native_protocol(
        self, channel: int, protocol: bytes, sample: Sample, *, timeout: float | None = None
    ) -> None:
        """
        Start a Neware BTS Step File on an idle channel.

        Args:
          channel: The channel number.
          protocol: The step file's XML bytes.
          sample: The cell under test.
          timeout: The longest to wait for the server, in seconds.

        Raises:
          InvalidParameterError: If the step file or sample is rejected; `parameter` names which.
          ChannelBusyError: If the channel is running or paused a protocol.
          ChannelNotClearedError: If the channel holds an ended run.
          ChannelUnavailableError: If the channel is unavailable.
        """
        with translate_errors(ERRORS):
            await self._ns.StartNativeProtocol(
                Channel=channel, Protocol=protocol, Sample=to_wire(sample), timeout=ms(timeout)
            )

    async def validate_native_protocol(
        self, channel: int, protocol: bytes, sample: Sample, *, timeout: float | None = None
    ) -> NativeProtocolSummary:
        """
        Check a Neware BTS Step File as `start_native_protocol` would, without starting it.

        Raises:
          InvalidParameterError: If the step file or sample is rejected; `parameter` names which.
        """
        with translate_errors(ERRORS):
            responses = await self._ns.ValidateNativeProtocol(
                Channel=channel, Protocol=protocol, Sample=to_wire(sample), timeout=ms(timeout)
            )
        return from_wire(NativeProtocolSummary, response(responses, "Summary"))


__all__ = ["ERRORS", "FEATURE", "NewareProtocolControllerClient"]
