"""
neware8 points as OmniCycler data points, in BDF quantities.

neware8 decodes V, A (positive charging), Ah, Wh and s, and accumulates capacity
and energy from the device's per-step counters. Unix time is the host's receipt
time of the test start plus test time, because the controller's calendar has no
established time zone. The main-record temperature has no established sensor
placement and is not reported; every optional quantity is NaN.
"""

import math

import neware8
from omnicycler.features.types import DataPoint

NAN = math.nan


def to_data_point(
    point: neware8.RecordedPoint, index: int, start_time: float, step_positions: dict[int, int]
) -> DataPoint:
    """Convert one neware8 record into a data point with the given record index."""
    return DataPoint(
        record_index=index,
        test_time=point.test_time_second,
        unix_time=start_time + point.test_time_second,
        voltage=point.voltage_volt,
        current=_value(point.current_ampere),
        cycle_count=point.cycle,
        step_count=point.step_count,
        protocol_step=step_positions.get(point.step_id, point.step_id),
        charging_capacity=_value(point.charging_capacity_ah),
        discharging_capacity=_value(point.discharging_capacity_ah),
        charging_energy=_value(point.charging_energy_wh),
        discharging_energy=_value(point.discharging_energy_wh),
        ambient_temperature=NAN,
        surface_temperature=NAN,
        temperature_t1=NAN,
        temperature_t2=NAN,
        temperature_t3=NAN,
        temperature_t4=NAN,
        temperature_t5=NAN,
        ambient_pressure=NAN,
        applied_pressure=NAN,
        surface_pressure=NAN,
        internal_resistance=NAN,
        ac_internal_resistance=NAN,
        dc_internal_resistance=NAN,
        frequency=NAN,
        real_impedance=NAN,
        imaginary_impedance=NAN,
    )


def _value(value: float | None) -> float:
    return NAN if value is None else value


__all__ = ["to_data_point"]
