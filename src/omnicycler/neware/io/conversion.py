"""
Conversion of aurora-unicycler protocols into Neware BTS82 programs.

A protocol becomes a BTS Step File through aurora-unicycler's own Neware
exporter, and that file is compiled by neware8 for the target channel, exactly
as a start would. neware8 accepts only a protected subset of step files: every
active step needs a time limit, a recording interval and voltage and current
protections, and every value must convert exactly into native units. This module
makes a valid unicycler protocol fit that subset where it can, and says how:

- Current safety limits the protocol leaves unset are filled from the channel's
  rated current. Voltage limits are always set: omnicycler-features rejects a
  protocol without them.
- C-rates become absolute currents, and every value is rounded to the native
  resolution (0.1 mV, 1 ms, one native current unit). Changes beyond float noise
  are reported as warnings.
- A step without `until_time_s`, a constant-voltage step that does not follow a
  constant-current step ending at its voltage, or a constant-voltage step without
  a cutoff current cannot be expressed and is rejected.

Units here are unicycler's (V, mA, mAh, s) and Neware's native ones; nothing is
converted to BDF units in this module.
"""

import dataclasses
import math
import warnings

import neware8
from aurora_unicycler import (
    ConstantCurrent,
    ConstantVoltage,
    CyclingProtocol,
    OpenCircuitVoltage,
    ProtocolMethodWarning,
    RecordParams,
    Step,
    Tag,
)
from neware8.recipe import RecipeError

from .errors import NativeProtocolError

_FLOAT_NOISE = 1e-9
"""Relative differences below this are float formatting noise, not rounding."""


@dataclasses.dataclass(frozen=True)
class ConvertedProtocol:
    """
    A unicycler protocol as a Neware program for one channel.

    Attributes:
      xml: The BTS Step File the program was compiled from.
      recipe: The neware8 recipe of `xml`.
      compiled: The native program, compiled for the channel.
      step_positions: The unicycler method position, counting from one, of each native step ID.
      warnings: How the protocol was adapted to the cycler.
    """

    xml: bytes
    recipe: neware8.Recipe
    compiled: neware8.CompiledRecipe
    step_positions: dict[int, int]
    warnings: list[str]


def convert_protocol(protocol: CyclingProtocol, profile: neware8.ChannelProfile) -> ConvertedProtocol:
    """
    Convert a validated protocol, with its sample merged in, into a program for one channel.

    Args:
      protocol: The protocol; it is not modified.
      profile: The channel's ratings and current scale.

    Returns:
      The program and how the protocol was adapted.

    Raises:
      NativeProtocolError: If the protocol cannot be expressed as a Neware program for this channel.
    """
    adapted = protocol.model_copy(deep=True)
    notes: list[str] = []
    resolution = _Resolution(profile.current_scale, notes)
    capacity_mah = adapted.sample.capacity_mAh or 0.0

    _fill_safety(adapted, profile, notes)
    _round_settings(adapted, resolution)
    adapted.method = [
        _adapt_step(position, step, capacity_mah, resolution) for position, step in enumerate(adapted.method, 1)
    ]
    _check_constant_voltage(adapted)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ProtocolMethodWarning)
        try:
            text = adapted.to_neware_xml()
        except (ValueError, NotImplementedError) as error:
            msg = f"The protocol cannot be written as a Neware step file: {error}"
            raise NativeProtocolError(msg) from None
    notes.extend(str(warning.message) for warning in caught if issubclass(warning.category, UserWarning))

    xml = text.encode("utf-8")
    recipe, compiled = compile_step_file(xml, profile)
    return ConvertedProtocol(
        xml=xml,
        recipe=recipe,
        compiled=compiled,
        step_positions=step_positions(protocol),
        warnings=notes,
    )


def compile_step_file(xml: bytes, profile: neware8.ChannelProfile) -> tuple[neware8.Recipe, neware8.CompiledRecipe]:
    """
    Compile a BTS Step File for one channel, offline.

    Raises:
      NativeProtocolError: If neware8 rejects the step file for this channel.
    """
    try:
        recipe = neware8.Recipe(xml)
        return recipe, recipe.compile(profile)
    except (RecipeError, ValueError, TypeError) as error:
        msg = f"The Neware step file is not accepted for this channel: {error}"
        raise NativeProtocolError(msg) from None


def step_positions(protocol: CyclingProtocol) -> dict[int, int]:
    """
    Map each native step ID to its position in the unicycler method list.

    The exporter numbers the steps after removing tags and appends an End step,
    which maps to the last method position.
    """
    positions = [position for position, step in enumerate(protocol.method, 1) if not isinstance(step, Tag)]
    mapping = dict(enumerate(positions, 1))
    mapping[len(positions) + 1] = len(protocol.method)
    return mapping


class _Resolution:
    """Rounds unicycler values to the native resolution and notes material changes."""

    def __init__(self, current_scale: int, notes: list[str]) -> None:
        self._current_step_ma = 1 / current_scale
        self._notes = notes

    def voltage(self, value: float | None, where: str) -> float | None:
        return self._round(value, 1e-4, where, "V")

    def time(self, value: float | None, where: str) -> float | None:
        return self._round(value, 1e-3, where, "s")

    def current(self, value: float | None, where: str) -> float | None:
        return self._round(value, self._current_step_ma, where, "mA")

    def capacity(self, value: float | None, where: str) -> float | None:
        # Native capacity is mA*s times the current scale.
        return self._round(value, self._current_step_ma / 3600, where, "mAh")

    def _round(self, value: float | None, step: float, where: str, unit: str) -> float | None:
        if value is None:
            return None
        rounded = round(value / step) * step
        rounded = float(f"{rounded:.12g}")
        if not math.isclose(rounded, value, rel_tol=_FLOAT_NOISE, abs_tol=step * _FLOAT_NOISE):
            self._notes.append(
                f"{where} was rounded from {value:g} {unit} to {rounded:g} {unit}, the cycler's resolution."
            )
        return rounded


def _fill_safety(protocol: CyclingProtocol, profile: neware8.ChannelProfile, notes: list[str]) -> None:
    safety = protocol.safety
    rated_current_ma = profile.current_rating_a * 1000
    defaults = {"max_current_mA": rated_current_ma, "min_current_mA": -rated_current_ma}
    filled = {name: value for name, value in defaults.items() if getattr(safety, name) is None}
    if not filled:
        return
    protocol.safety = safety.model_copy(update=filled)
    settings = ", ".join(f"{name}={value:g}" for name, value in filled.items())
    notes.append(f"Safety limits the protocol leaves unset were filled from the channel's ratings: {settings}.")


def _round_settings(protocol: CyclingProtocol, resolution: _Resolution) -> None:
    safety = protocol.safety
    protocol.safety = safety.model_copy(
        update={
            "max_voltage_V": resolution.voltage(safety.max_voltage_V, "safety.max_voltage_V"),
            "min_voltage_V": resolution.voltage(safety.min_voltage_V, "safety.min_voltage_V"),
            "max_current_mA": resolution.current(safety.max_current_mA, "safety.max_current_mA"),
            "min_current_mA": resolution.current(safety.min_current_mA, "safety.min_current_mA"),
            "max_capacity_mAh": resolution.capacity(safety.max_capacity_mAh, "safety.max_capacity_mAh"),
            "delay_s": resolution.time(safety.delay_s, "safety.delay_s"),
        }
    )
    protocol.record = _round_record(protocol.record, resolution, "record")


def _round_record(record: RecordParams, resolution: _Resolution, where: str) -> RecordParams:
    return record.model_copy(
        update={
            "time_s": resolution.time(record.time_s, f"{where}.time_s"),
            "voltage_V": resolution.voltage(record.voltage_V, f"{where}.voltage_V"),
            "current_mA": resolution.current(record.current_mA, f"{where}.current_mA"),
        }
    )


def _adapt_step[S: Step](position: int, step: S, capacity_mah: float, resolution: _Resolution) -> S:
    where = f"Step {position}"
    update: dict[str, object] = {}
    if isinstance(step, ConstantCurrent | ConstantVoltage | OpenCircuitVoltage):
        if step.until_time_s is None:
            msg = f"{where} has no until_time_s; every step of a Neware program needs a time limit."
            raise NativeProtocolError(msg)
        update["until_time_s"] = resolution.time(step.until_time_s, f"{where} until_time_s")
        if step.record is not None:
            update["record"] = _round_record(step.record, resolution, f"{where} record")
    if isinstance(step, ConstantCurrent):
        current = step.rate_C * capacity_mah if step.rate_C else step.current_mA
        update["rate_C"] = None
        update["current_mA"] = resolution.current(current, f"{where} current")
        update["until_voltage_V"] = resolution.voltage(step.until_voltage_V, f"{where} until_voltage_V")
    if isinstance(step, ConstantVoltage):
        cutoff = step.until_rate_C * capacity_mah if step.until_rate_C else step.until_current_mA
        update["until_rate_C"] = None
        update["until_current_mA"] = resolution.current(cutoff, f"{where} cutoff current")
        update["voltage_V"] = resolution.voltage(step.voltage_V, f"{where} voltage_V")
    return step.model_copy(update=update) if update else step


def _check_constant_voltage(protocol: CyclingProtocol) -> None:
    previous: Step | None = None
    for position, step in enumerate(protocol.method, 1):
        if isinstance(step, ConstantVoltage):
            if not (isinstance(previous, ConstantCurrent) and previous.until_voltage_V == step.voltage_V):
                msg = (
                    f"Step {position} is constant voltage without a constant-current step ending at "
                    f"{step.voltage_V:g} V before it; a Neware CV step takes its current limit from that step."
                )
                raise NativeProtocolError(msg)
            if not step.until_current_mA:
                msg = f"Step {position} is constant voltage without a cutoff current, which a Neware CV step needs."
                raise NativeProtocolError(msg)
        if not isinstance(step, Tag):
            previous = step


__all__ = ["ConvertedProtocol", "compile_step_file", "convert_protocol", "step_positions"]
