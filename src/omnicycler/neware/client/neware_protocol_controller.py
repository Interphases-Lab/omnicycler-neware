import uuid

from omnicycler.features.client.base import ErrorMap, error_map, from_wire, ms, response, to_wire, translate_errors
from omnicycler.features.errors import (
    ChannelBusyError,
    ChannelNotClearedError,
    ChannelUnavailableError,
    RunIdInUseError,
)
from omnicycler.features.types import Sample
from sila.client import FeatureNamespace

from ..identifiers import feature_identifier
from ..types import NativeProtocolSummary

FEATURE = feature_identifier("NewareProtocolController")
ERRORS: ErrorMap = error_map(ChannelBusyError, ChannelNotClearedError, ChannelUnavailableError, RunIdInUseError)


class NewareProtocolControllerClient:
    """Typed client of `NewareProtocolController`: run native Neware step files."""

    def __init__(self, namespace: FeatureNamespace) -> None:
        self._ns = namespace

    async def start_native_protocol(
        self,
        channel: int,
        protocol: bytes,
        sample: Sample,
        *,
        run_id: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """
        Start a Neware BTS Step File on an idle channel, as a new run.

        If the outcome is unknown, call again with the same `run_id`: a start of the run the channel already
        holds succeeds without effect.

        Args:
          channel: The channel number.
          protocol: The step file's XML bytes.
          sample: The cell under test.
          run_id: The new run's identifier; a fresh UUID if omitted.
          timeout: The longest to wait for the server, in seconds.

        Returns:
          The run's identifier.

        Raises:
          InvalidParameterError: If the step file or sample is rejected; `parameter` names which.
          ChannelBusyError: If the channel is running or paused another run.
          ChannelNotClearedError: If the channel holds another, ended run.
          ChannelUnavailableError: If the channel is unavailable.
          RunIdInUseError: If another channel holds a run with this identifier.
        """
        run_id = run_id or str(uuid.uuid4())
        with translate_errors(ERRORS):
            await self._ns.StartNativeProtocol(
                Channel=channel, RunId=run_id, Protocol=protocol, Sample=to_wire(sample), timeout=ms(timeout)
            )
        return run_id

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
