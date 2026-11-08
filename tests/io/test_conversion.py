import json

import neware8
import pytest
from omnicycler.features.protocol import parse_protocol
from omnicycler.features.types import Sample

from omnicycler.neware.io.conversion import compile_step_file, convert_protocol, step_positions
from omnicycler.neware.io.errors import NativeProtocolError

PROFILE = neware8.ChannelProfile(neware8.ChannelAddress(1, 1), 0, 5.0, 0.01, 10000, -10)
SAMPLE = Sample(name="cell", nominal_capacity=0.005)
VOLTAGE_LIMITS = {"min_voltage_V": 2.5, "max_voltage_V": 4.3}


def protocol(method, *, safety=None, **extra):
    document = {"record": {"time_s": 10}, "safety": safety or VOLTAGE_LIMITS, "method": method, **extra}
    return parse_protocol(json.dumps(document).encode(), SAMPLE).protocol


def native(converted):
    return {step.step_id: step for step in converted.compiled.steps}


def test_unset_current_limits_are_filled_from_the_channel_rating():
    converted = convert_protocol(protocol([{"step": "open_circuit_voltage", "until_time_s": 60}]), PROFILE)
    step = native(converted)[1]
    assert step.values["protect_voltage_upper"].value == 43000  # the protocol's 4.3 V, in 0.1 mV
    assert step.values["protect_voltage_lower"].value == 25000
    assert step.values["protect_current_upper"].value == 10 * 10000  # 10 mA at scale 10000
    assert step.values["protect_current_lower"].value == -10 * 10000
    assert any("filled from the channel's ratings" in warning for warning in converted.warnings)


def test_explicit_safety_limits_are_kept_without_a_warning():
    safety = {"max_voltage_V": 4.3, "min_voltage_V": 2.5, "max_current_mA": 6, "min_current_mA": -6}
    converted = convert_protocol(
        protocol([{"step": "open_circuit_voltage", "until_time_s": 60}], safety=safety), PROFILE
    )
    assert native(converted)[1].values["protect_voltage_upper"].value == 43000
    assert converted.warnings == []


def test_c_rates_become_rounded_absolute_currents():
    converted = convert_protocol(
        protocol([{"step": "constant_current", "rate_C": 1 / 3, "until_voltage_V": 4.2, "until_time_s": 3600}]),
        PROFILE,
    )
    assert native(converted)[1].values["current"].value == 16667  # 1.6667 mA
    assert any("rounded from 1.66667 mA to 1.6667 mA" in warning for warning in converted.warnings)


def test_cc_then_cv_and_tags_map_native_steps_to_protocol_positions():
    method = [
        {"step": "tag", "tag": "start"},
        {"step": "constant_current", "rate_C": 0.5, "until_voltage_V": 4.2, "until_time_s": 3600},
        {"step": "constant_voltage", "voltage_V": 4.2, "until_rate_C": 0.05, "until_time_s": 3600},
        {"step": "loop", "loop_to": "start", "cycle_count": 2},
    ]
    parsed = protocol(method)
    converted = convert_protocol(parsed, PROFILE)
    assert converted.compiled.step_count == 4  # CC, CV, Cycle, End
    assert step_positions(parsed) == {1: 2, 2: 3, 3: 4, 4: 4}
    assert native(converted)[2].values["cutoff_current"].value == 2500  # 0.25 mA


@pytest.mark.parametrize(
    ("method", "message"),
    [
        ([{"step": "constant_current", "rate_C": 0.5, "until_voltage_V": 4.2}], "no until_time_s"),
        ([{"step": "constant_voltage", "voltage_V": 4.2, "until_current_mA": 0.1, "until_time_s": 60}], "constant"),
        (
            [
                {"step": "constant_current", "current_mA": 1, "until_voltage_V": 4.2, "until_time_s": 60},
                {"step": "constant_voltage", "voltage_V": 4.2, "until_time_s": 60},
            ],
            "cutoff current",
        ),
    ],
)
def test_protocols_neware_cannot_express_are_rejected(method, message):
    with pytest.raises(NativeProtocolError, match=message):
        convert_protocol(protocol(method), PROFILE)


def test_current_at_the_rating_is_rejected_by_the_compiler():
    method = [{"step": "constant_current", "current_mA": 10, "until_time_s": 60}]
    with pytest.raises(NativeProtocolError, match="not accepted"):
        convert_protocol(protocol(method), PROFILE)


def test_invalid_step_file_is_rejected():
    with pytest.raises(NativeProtocolError):
        compile_step_file(b"<root/>", PROFILE)
