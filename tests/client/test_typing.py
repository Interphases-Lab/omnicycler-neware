"""The public client API resolves to the intended types; ty fails the build if any becomes `Any`."""

import collections.abc
import typing

from omnicycler.features.types import Sample

from omnicycler.neware.client import NewareClient
from omnicycler.neware.types import NativeProtocolSummary, UnitInformation

from .step_files import discharge_cycles

SAMPLE = Sample(name="typed-cell", nominal_capacity=0.005)


async def test_brand_client_types(neware):
    client: NewareClient = neware.client
    typing.assert_type(
        await client.protocols.validate_native_protocol(1, discharge_cycles(), SAMPLE), NativeProtocolSummary
    )
    typing.assert_type(await client.controller.get_controller_identifier(), str)
    typing.assert_type(await client.controller.get_clock_setting_requested(), bool)
    typing.assert_type(await client.controller.get_units(), list[int])
    typing.assert_type(await client.controller.get_unit_information(1), UnitInformation)
    typing.assert_type(await client.settings.get_upload_interval(), int)
    typing.assert_type(await client.settings.set_upload_interval(5), None)
    typing.assert_type(await client.settings.synchronize_clock(), None)
    async with client.settings.subscribe_upload_interval() as intervals:
        typing.assert_type(intervals, collections.abc.AsyncIterator[int])
    typing.assert_type(await client.protocols.start_native_protocol(1, discharge_cycles(), SAMPLE), None)
