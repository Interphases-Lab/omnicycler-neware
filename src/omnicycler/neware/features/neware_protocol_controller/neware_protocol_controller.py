import typing

from omnicycler.features.errors import (
    ChannelBusyError,
    ChannelNotClearedError,
    ChannelUnavailableError,
    InvalidSampleError,
)
from omnicycler.features.parameters import ChannelNumber, restrict_channels
from omnicycler.features.types import Sample
from unitelabs.cdk import sila

from ...backend import NewareBackend
from ...identifiers import CATEGORY, ORIGINATOR
from ...io.errors import NativeProtocolError
from ...types import NativeProtocolSummary

StepFile = typing.Annotated[bytes, sila.constraints.ContentType("application", "xml")]
"""A Neware BTS Step File as XML bytes."""


class NewareProtocolController(sila.Feature):
    """
    Run native Neware BTS step files on the channels of the cycler.

    A step file is the XML a Neware BTS client saves (a "Step File" of version 17 or 18), within the protected subset
    this server compiles: constant-current, constant-voltage and CCCV charge and discharge, rest, finite cycles and
    End, each active step with a time limit, a recording interval and voltage and current protections, and currents
    as absolute values. Use it for programs the aurora-unicycler format cannot express; anything it can express is
    better started with `ChannelController.StartProtocol`, which works on every OmniCycler server.

    A run started here follows the standard channel lifecycle. It appears in `ChannelController` and
    `MeasurementProvider` like any other run, with `RunInformation.ProtocolFormat` `native`, the step file as
    `RunInformation.Protocol` and the native step number as `ProtocolStep`. Pause, resume, stop and clear it with
    `ChannelController`.
    """

    def __init__(self, backend: NewareBackend) -> None:
        super().__init__(originator=ORIGINATOR, category=CATEGORY)
        self.backend = backend

    @typing.override
    async def on_before_start(self) -> None:
        channels = [information.channel for information in await self.backend.get_channels()]
        restrict_channels(self, [self.start_native_protocol, self.validate_native_protocol], channels)

    @sila.UnobservableCommand(errors=[ChannelBusyError, ChannelNotClearedError, ChannelUnavailableError])
    async def start_native_protocol(self, channel: ChannelNumber, protocol: StepFile, sample: Sample) -> None:
        """
        Start a Neware step file on an idle channel.

        The step file is compiled for the channel before anything happens on it; a step file this server cannot
        compile is rejected as a validation error. The sample names the run and is kept with it; C-rates of the
        step file are not recalculated from it. Once started, the channel reports `running`.

        Args:
          Channel: The channel to start the step file on.
          Protocol: The Neware BTS Step File as XML.
          Sample: The cell under test.
        """
        await self.backend.start_native_protocol(channel, protocol, sample)

    @sila.UnobservableCommand()
    async def validate_native_protocol(
        self,
        channel: ChannelNumber,
        protocol: StepFile,
        sample: Sample,  # noqa: ARG002  # checked by the validator, as for StartNativeProtocol
    ) -> NativeProtocolSummary:
        """
        Check a Neware step file exactly as `StartNativeProtocol` would, without starting it.

        A step file that cannot be started is rejected as a validation error.

        Args:
          Channel: The channel the step file is meant for.
          Protocol: The Neware BTS Step File as XML.
          Sample: The cell under test.

        Returns:
          Summary: The compiled program's step count and longest duration.
        """
        return self.backend.validate_native_protocol(channel, protocol)

    @validate_native_protocol.validator
    @start_native_protocol.validator
    async def _check_step_file(self, channel: int, protocol: bytes, sample: Sample) -> None:
        try:
            self.backend.validate_sample(sample)
        except InvalidSampleError as error:
            raise sila.errors.ValidationError(str(error), "sample") from None
        try:
            self.backend.validate_native_protocol(channel, protocol)
        except NativeProtocolError as error:
            raise sila.errors.ValidationError(str(error), "protocol") from None
