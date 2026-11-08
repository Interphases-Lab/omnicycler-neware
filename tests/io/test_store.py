import dataclasses
import json
import math
import sqlite3
import struct
import time

import neware8
import pytest
from neware8.messages import HistoryBatch, HistoryRecord

from omnicycler.neware.io.records import to_data_point
from omnicycler.neware.io.store import FILENAME, NewareStore, ProtocolKind, RunEntry

CONTROLLER = bytes(range(16))
ADDRESS = neware8.ChannelAddress(1, 2)
RUN = RunEntry(
    run_id="0b0f4f39-8a0e-4b4e-9b39-5bc3e8f29a11",
    unit=1,
    channel=2,
    sample_name="cell",
    nominal_capacity=0.005,
    kind=ProtocolKind.NATIVE,
    protocol=b"<xml/>",
    step_positions={1: 1, 2: 2},
    sample_identifier="CELL-9",
)
MAH = 36_000_000_000 // 1000  # one mAh in raw counter units at scale 10000


def raw_record(sequence, *, test_id=7, channel=2, step=1, charge=0, voltage=36000, flag=0x55):  # noqa: PLR0913
    values = [
        flag, 1, channel, 0, test_id, sequence, 1, step, 1, step, 0x10, sequence * 1000,
        voltage, -10000, 0, 250, charge, 0, charge * 4, 0, 2026, 11, 7, 12, 0, 0, -10, sequence * 1000,
    ]  # fmt: skip
    return HistoryRecord.FORMAT.pack(*values)


def history(*records, token=0x1000):
    payload = struct.pack("<BI", len(records), token) + b"".join(records)
    return HistoryBatch.from_payload(payload)


@pytest.fixture
async def store(tmp_path):
    result = NewareStore(tmp_path)
    await result.open()
    await result.bind(CONTROLLER)
    yield result
    await result.close()


async def started(store, run=RUN, test_id=7):
    await store.attempt(run)
    test = neware8.StartedTest(run.address, test_id, 1, None, 1_000_000_000_000)
    await store.register((test,))
    registered = store.run_on(run.address, test_id)
    assert registered is not None
    return registered


async def test_a_store_belongs_to_one_controller(store):
    await store.bind(CONTROLLER)
    with pytest.raises(neware8.StorageError, match="belongs to controller"):
        await store.bind(bytes(16))


async def test_attempts_become_runs_once_registered(store):
    await store.attempt(RUN)
    assert store.run_on(ADDRESS, 7) is None
    other = dataclasses.replace(RUN, run_id="1b0f4f39-8a0e-4b4e-9b39-5bc3e8f29a11")
    run = await started(store, other)  # replaces the attempt that got no TestID
    assert (run.run_id, run.test_id, run.started_ns) == (other.run_id, 7, 1_000_000_000_000)
    assert store.record_count(run) == 0


async def test_commit_keeps_main_records_of_registered_tests_and_the_checkpoint(store):
    run = await started(store)
    await store.commit(
        history(
            raw_record(1),
            raw_record(2),
            raw_record(1, test_id=99),  # another test
            raw_record(1, channel=3),  # another channel
            raw_record(3, flag=0xAA),  # an event record
            token=0x2000,
        )
    )
    assert store.record_count(run) == 2
    assert await store.checkpoint() == 0x2000


async def test_resent_records_are_accepted_and_conflicts_refuse_the_batch(store):
    run = await started(store)
    await store.commit(history(raw_record(1), raw_record(2), token=1))
    await store.commit(history(raw_record(2), raw_record(3), token=2))  # a resend overlapping
    assert store.record_count(run) == 3
    with pytest.raises(neware8.StorageError, match="Conflicting history"):
        await store.commit(history(raw_record(4), raw_record(3, voltage=1), token=3))
    assert store.record_count(run) == 3  # rolled back
    assert await store.checkpoint() == 2


async def test_runs_and_history_survive_a_restart(tmp_path):
    first = NewareStore(tmp_path)
    await first.open()
    await first.bind(CONTROLLER)
    run = await started(first)
    run = await first.mark_stopped(run)
    await first.commit(history(raw_record(1), token=5))
    await first.close()

    second = NewareStore(tmp_path)
    await second.open()
    try:
        assert second.run_on(ADDRESS, 7) == run
        assert run.sample_identifier == "CELL-9"
        assert await second.checkpoint() == 5
        assert second.record_count(run) == 1
        await second.commit(history(raw_record(2), token=6))  # numbering continues where it stopped
        assert [point.record_index for point in await second.read(run, 0, 10)] == [0, 1]
    finally:
        await second.close()


async def test_reads_number_records_without_gaps_and_resume_totals(store):
    run = await started(store)
    await store.commit(history(*(raw_record(s, charge=s * MAH) for s in (1, 2, 4, 5)), token=1))
    whole = await store.read(run, 0, 10)
    assert [p.record_index for p in whole] == [0, 1, 2, 3]
    assert [p.test_time for p in whole] == [1.0, 2.0, 4.0, 5.0]
    assert whole[1].charging_capacity == pytest.approx(0.002)
    assert math.isnan(whole[2].charging_capacity)  # after the gap, the total is unknown
    assert whole[0].unix_time == pytest.approx(1001.0)
    first, rest = await store.read(run, 0, 2), await store.read(run, 2, 10)
    assert [p.record_index for p in first + rest] == [0, 1, 2, 3]
    store._cursors.clear()
    assert (await store.read(run, 1, 1))[0].charging_capacity == pytest.approx(0.002)
    assert await store.read(run, 4, 10) == []


async def test_late_history_is_kept_but_never_shifts_indices(store):
    run = await started(store)
    await store.commit(history(raw_record(1, charge=MAH), raw_record(3, charge=MAH), token=1))
    before = await store.read(run, 0, 10)
    assert math.isnan(before[1].charging_capacity)

    await store.commit(history(raw_record(2, charge=MAH), token=2))  # the controller resent older history

    after = await store.read(run, 0, 10)
    assert [(p.record_index, p.test_time) for p in after] == [(0, 1.0), (1, 3.0)]
    assert math.isnan(after[1].charging_capacity)  # the gap stays a gap
    assert store.record_count(run) == 2
    await store.commit(history(raw_record(4, charge=2 * MAH), token=3))
    assert [p.record_index for p in await store.read(run, 0, 10)] == [0, 1, 2]


async def test_delete_drops_the_run_and_its_records(store):
    run = await started(store)
    await store.commit(history(raw_record(1), token=1))
    await store.delete(run)
    assert store.run_on(ADDRESS, 7) is None
    await store.commit(history(raw_record(2), token=2))  # history of a deleted run is not kept
    assert store.record_count(run) == 0
    assert not store.holds(run.run_id)


async def test_a_schema_1_store_is_numbered_once_on_open(tmp_path):
    db = sqlite3.connect(tmp_path / FILENAME)
    db.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, unit INTEGER NOT NULL, channel INTEGER NOT NULL,
            sample_name TEXT NOT NULL, nominal_capacity REAL NOT NULL, kind TEXT NOT NULL,
            protocol BLOB NOT NULL, step_positions TEXT NOT NULL, stopped INTEGER NOT NULL,
            test_id INTEGER, started_ns INTEGER, charge_range INTEGER,
            UNIQUE (unit, channel, test_id)
        );
        CREATE TABLE records (
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL, raw BLOB NOT NULL,
            PRIMARY KEY (run_id, sequence)
        ) WITHOUT ROWID;
        PRAGMA user_version=1;
        """
    )
    with db:
        db.execute(
            "INSERT INTO runs VALUES (?, 1, 2, 'cell', 0.005, 'native', x'00', ?, 0, 7, 1000000000000, NULL)",
            (RUN.run_id, json.dumps({"1": 1})),
        )
        db.executemany(
            "INSERT INTO records VALUES (?, ?, ?)",
            [(RUN.run_id, sequence, raw_record(sequence)) for sequence in (5, 1, 2)],
        )
    db.close()

    store = NewareStore(tmp_path)
    await store.open()
    try:
        run = store.run_on(ADDRESS, 7)
        assert run is not None
        assert run.sample_identifier == ""
        assert store.record_count(run) == 3
        assert [p.test_time for p in await store.read(run, 0, 10)] == [1.0, 2.0, 5.0]
    finally:
        await store.close()


def test_data_points_use_bdf_units_and_nan_for_unknown_values():
    point = neware8.RecordedPoint(
        sequence=5,
        test_time_second=12.5,
        voltage_volt=3.7,
        current_ampere=-0.001,
        cycle=2,
        step_id=3,
        raw=b"",
        charging_capacity_ah=0.002,
        discharging_capacity_ah=None,
        charging_energy_wh=0.007,
        discharging_energy_wh=None,
        step_count=4,
    )
    data = to_data_point(point, 4, 1000.0, {3: 5})
    assert (data.record_index, data.test_time, data.unix_time) == (4, 12.5, 1012.5)
    assert (data.voltage, data.current, data.cycle_count, data.step_count, data.protocol_step) == (3.7, -0.001, 2, 4, 5)
    assert data.charging_capacity == 0.002
    assert math.isnan(data.discharging_capacity)
    assert math.isnan(data.ambient_temperature)
    unknown_current = to_data_point(neware8.RecordedPoint(1, 0.0, 3.6, None, 1, 9, b""), 0, time.time(), {})
    assert math.isnan(unknown_current.current)
    assert unknown_current.protocol_step == 9  # unmapped native steps keep their number
