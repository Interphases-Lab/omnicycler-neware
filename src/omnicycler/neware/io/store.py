"""
The server's own store of runs and their history, in one SQLite database.

neware8 is a driver: it hands every history batch to a `HistorySink` and
acknowledges it to the controller only after the sink committed it. This store
is that sink, and it also keeps what OmniCycler needs to describe a run: its
run ID, sample, protocol and step mapping, and whether a client stopped it.

A run is written in two steps. `attempt` stores its description before the
first device write of a start; `register` adds the TestID the controller
assigned, in the Start reply, before any of the test's history can arrive. Only
main-channel records of registered tests are kept, keyed by sequence. A resent
record with identical bytes is accepted again; the same sequence with other
bytes is a conflict that refuses the whole batch, so it is not acknowledged.

Records get their record index once, when they arrive, counting from zero
without gaps in the order of their sequence, and keep it for as long as the run
exists. A late record, whose sequence lies before an already numbered one (the
controller resent older history), is kept but never numbered or served: giving
it an index would shift every record after it. A gap it leaves makes the totals
after it NaN, as any history gap does. Clearing a run deletes it with its
records; the controller's own history is untouched.
"""

import asyncio
import collections
import copy
import dataclasses
import enum
import itertools
import json
import logging
import pathlib
import sqlite3
import threading

import neware8
from neware8.history import RunningTotals, decode, is_main
from neware8.messages import HistoryBatch, HistoryRecord
from omnicycler.features.types import DataPoint

from .records import to_data_point

logger = logging.getLogger(__name__)

FILENAME = "omnicycler-neware.sqlite"
SCHEMA_VERSION = 2
MAXIMAL_CURSORS = 64
"""Resumable totals positions kept in memory, so paged reads need not start from the first record."""


class ProtocolKind(enum.Enum):
    """How a run's protocol was given: as aurora-unicycler JSON or as a native Neware step file."""

    UNICYCLER = "unicycler"
    NATIVE = "native"


@dataclasses.dataclass(frozen=True)
class RunEntry:
    """
    A run started by this server.

    Attributes:
      run_id: The OmniCycler run ID, chosen by the client that started the run.
      unit: The channel's lower unit.
      channel: The channel within the unit.
      sample_name: The name of the cell under test.
      nominal_capacity: The nominal capacity of the cell, in Ah.
      kind: How the protocol was given.
      protocol: The protocol as given, with the sample merged in for unicycler protocols.
      step_positions: The protocol position of each native step ID.
      sample_identifier: The cell's identifier outside OmniCycler, or empty.
      stopped: Whether a client stopped the run.
      test_id: The TestID the controller assigned, once the start was acknowledged.
      started_ns: The host time of the controller's start acknowledgement.
      charge_range_raw: The channel's charge range, for records with a zero current range.
    """

    run_id: str
    unit: int
    channel: int
    sample_name: str
    nominal_capacity: float
    kind: ProtocolKind
    protocol: bytes
    step_positions: dict[int, int]
    sample_identifier: str = ""
    stopped: bool = False
    test_id: int | None = None
    started_ns: int | None = None
    charge_range_raw: int | None = None

    @property
    def address(self) -> neware8.ChannelAddress:
        """The channel of the run."""
        return neware8.ChannelAddress(self.unit, self.channel)


@dataclasses.dataclass
class _Numbering:
    """Where a run's numbering stands: the next record index, and the highest sequence numbered."""

    next_index: int
    highest_sequence: int


class NewareStore:
    """Runs and their history records; neware8's `HistorySink`. Use from one event loop."""

    def __init__(self, directory: str | pathlib.Path) -> None:
        self._path = pathlib.Path(directory) / FILENAME
        self._db: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._runs: dict[str, RunEntry] = {}
        self._numbering: dict[str, _Numbering] = {}
        self._cursors: collections.OrderedDict[tuple[str, int], RunningTotals] = collections.OrderedDict()

    async def open(self) -> None:
        """Open the database and load the runs."""
        await asyncio.to_thread(self._open)

    async def close(self) -> None:
        """Close the database."""
        if self._db is not None:
            db, self._db = self._db, None
            await asyncio.to_thread(db.close)

    # Runs.

    def run_on(self, address: neware8.ChannelAddress, test_id: int) -> RunEntry | None:
        """Return the run of a test on a channel, or `None` if this server did not start it."""
        return next(
            (run for run in self._runs.values() if run.address == address and run.test_id == test_id),
            None,
        )

    def holds(self, run_id: str) -> bool:
        """Whether the store holds a started run with this ID."""
        return run_id in self._runs

    async def attempt(self, run: RunEntry) -> None:
        """Store a run about to be started; replaces an earlier attempt on the channel that got no TestID."""
        await asyncio.to_thread(self._attempt, run)

    async def mark_stopped(self, run: RunEntry) -> RunEntry:
        """Record that a client stopped the run."""
        updated = dataclasses.replace(run, stopped=True)
        await asyncio.to_thread(self._execute, "UPDATE runs SET stopped=1 WHERE run_id=?", (run.run_id,))
        self._runs[run.run_id] = updated
        return updated

    async def delete(self, run: RunEntry) -> None:
        """Delete a run and its records."""
        await asyncio.to_thread(self._execute, "DELETE FROM runs WHERE run_id=?", (run.run_id,))
        self._runs.pop(run.run_id, None)
        await asyncio.to_thread(self._forget, run.run_id)

    def record_count(self, run: RunEntry) -> int:
        """Return the number of numbered records of a run, without reading the database."""
        numbering = self._numbering.get(run.run_id)
        return 0 if numbering is None else numbering.next_index

    async def read(self, run: RunEntry, from_index: int, count: int) -> list[DataPoint]:
        """
        Read up to `count` records of a run from record index `from_index` on, as data points.

        A step-boundary record whose following record has not arrived yet is withheld, so fewer
        records may be returned than are stored.
        """
        return await asyncio.to_thread(self._read, run, from_index, count)

    # neware8 HistorySink.

    async def bind(self, controller: bytes) -> None:
        """Accept the controller's GUID; refuse a store that belongs to another controller."""
        await asyncio.to_thread(self._bind, controller)

    async def register(self, tests: tuple[neware8.StartedTest, ...]) -> None:
        """Give the attempted runs on these channels their TestIDs."""
        for run in await asyncio.to_thread(self._register, tests):
            self._runs[run.run_id] = run
            self._numbering.setdefault(run.run_id, _Numbering(0, 0))

    async def commit(self, batch: HistoryBatch) -> None:
        """Store the batch's records of registered tests and its token, durably, in one transaction."""
        owners = {
            (run.unit, run.channel, run.test_id): run.run_id for run in self._runs.values() if run.test_id is not None
        }
        await asyncio.to_thread(self._commit, batch, owners)

    async def checkpoint(self) -> int | None:
        """The token of the last committed batch."""
        value = await asyncio.to_thread(self._metadata, "checkpoint")
        return None if value is None else int(value)

    # Database work, in worker threads.

    def _connection(self) -> sqlite3.Connection:
        if self._db is None:
            msg = "The run store is closed."
            raise neware8.StorageError(msg)
        return self._db

    def _open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._path, check_same_thread=False)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1, SCHEMA_VERSION}:
            db.close()
            msg = f"Unsupported run store schema {version} in {self._path}; expected {SCHEMA_VERSION}."
            raise neware8.StorageError(msg)
        if version == 1:
            _migrate_from_1(db)
        db.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, unit INTEGER NOT NULL, channel INTEGER NOT NULL,
                sample_name TEXT NOT NULL, nominal_capacity REAL NOT NULL, kind TEXT NOT NULL,
                protocol BLOB NOT NULL, step_positions TEXT NOT NULL, stopped INTEGER NOT NULL,
                test_id INTEGER, started_ns INTEGER, charge_range INTEGER,
                sample_identifier TEXT NOT NULL DEFAULT '',
                UNIQUE (unit, channel, test_id)
            );
            CREATE TABLE IF NOT EXISTS records (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL, raw BLOB NOT NULL, record_index INTEGER,
                PRIMARY KEY (run_id, sequence)
            ) WITHOUT ROWID;
            CREATE UNIQUE INDEX IF NOT EXISTS records_by_index ON records (run_id, record_index);
            PRAGMA user_version={SCHEMA_VERSION};
            """
        )
        self._db = db
        self._runs = {
            run.run_id: run for run in map(_run_from_row, db.execute("SELECT * FROM runs WHERE test_id IS NOT NULL"))
        }
        self._numbering = {run_id: _Numbering(0, 0) for run_id in self._runs}
        for run_id, highest_index, highest_sequence in db.execute(
            "SELECT run_id, max(record_index), max(sequence) FROM records "
            "WHERE record_index IS NOT NULL GROUP BY run_id"
        ):
            if run_id in self._numbering:
                self._numbering[run_id] = _Numbering(highest_index + 1, highest_sequence)

    def _execute(self, sql: str, parameters: tuple[object, ...]) -> None:
        with self._lock, self._connection() as db:
            db.execute(sql, parameters)

    def _metadata(self, key: str) -> str | None:
        with self._lock:
            row = self._connection().execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return None if row is None else row[0]

    def _bind(self, controller: bytes) -> None:
        with self._lock, self._connection() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='controller'").fetchone()
            if row is not None and row[0] != controller.hex():
                msg = f"The run store {self._path} belongs to controller {row[0]}, not {controller.hex()}."
                raise neware8.StorageError(msg)
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('controller', ?)", (controller.hex(),))

    def _attempt(self, run: RunEntry) -> None:
        with self._lock, self._connection() as db:
            db.execute("DELETE FROM runs WHERE unit=? AND channel=? AND test_id IS NULL", (run.unit, run.channel))
            db.execute(
                "INSERT INTO runs (run_id, unit, channel, sample_name, nominal_capacity, kind, protocol, "
                "step_positions, stopped, sample_identifier) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.unit,
                    run.channel,
                    run.sample_name,
                    run.nominal_capacity,
                    run.kind.value,
                    run.protocol,
                    json.dumps(run.step_positions),
                    int(run.stopped),
                    run.sample_identifier,
                ),
            )

    def _register(self, tests: tuple[neware8.StartedTest, ...]) -> list[RunEntry]:
        with self._lock, self._connection() as db:
            for test in tests:
                address = test.address
                db.execute(
                    "UPDATE runs SET test_id=?, started_ns=?, charge_range=? "
                    "WHERE unit=? AND channel=? AND test_id IS NULL",
                    (test.test_id, test.started_at_ns, test.charge_range_raw, address.unit, address.channel),
                )
            registered = [
                db.execute(
                    "SELECT * FROM runs WHERE unit=? AND channel=? AND test_id=?",
                    (test.address.unit, test.address.channel, test.test_id),
                ).fetchone()
                for test in tests
            ]
        return [_run_from_row(row) for row in registered if row is not None]

    def _commit(self, batch: HistoryBatch, owners: dict[tuple[int, int, int], str]) -> None:
        late: collections.Counter[str] = collections.Counter()
        numbering: dict[str, _Numbering] = {}  # of the runs this batch numbers records of
        with self._lock, self._connection() as db:
            for record in batch.records:
                run_id = owners.get((record.unit, record.channel, record.test_id))
                if run_id is None or not is_main(record):
                    continue
                stored = db.execute(
                    "SELECT raw FROM records WHERE run_id=? AND sequence=?", (run_id, record.sequence)
                ).fetchone()
                if stored is not None:
                    if bytes(stored[0]) != record.raw:
                        msg = f"Conflicting history for run {run_id} at sequence {record.sequence}."
                        raise neware8.StorageError(msg)
                    continue
                if run_id not in numbering:
                    numbering[run_id] = dataclasses.replace(self._numbering.get(run_id) or _Numbering(0, 0))
                state = numbering[run_id]
                index = None
                if record.sequence > state.highest_sequence:
                    index = state.next_index
                    state.next_index += 1
                    state.highest_sequence = record.sequence
                else:
                    late[run_id] += 1
                db.execute("INSERT INTO records VALUES (?, ?, ?, ?)", (run_id, record.sequence, record.raw, index))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('checkpoint', ?)", (str(batch.token),))
        # Only once the transaction committed, and only for runs that still exist.
        self._numbering.update({run_id: state for run_id, state in numbering.items() if run_id in self._runs})
        for run_id, count in late.items():
            logger.warning(
                "Run %s received %d late records, before records already numbered; they are kept but not served.",
                run_id,
                count,
            )

    def _read(self, run: RunEntry, from_index: int, count: int) -> list[DataPoint]:
        with self._lock:
            db = self._connection()
            totals = self._totals_at(db, run, from_index)
            previous = None
            if from_index:
                row = db.execute(
                    "SELECT raw FROM records WHERE run_id=? AND record_index=?", (run.run_id, from_index - 1)
                ).fetchone()
                if row is None:
                    return []
                previous = HistoryRecord.from_bytes(bytes(row[0]))
            rows = db.execute(
                "SELECT raw FROM records WHERE run_id=? AND record_index>=? AND record_index<? ORDER BY record_index",
                (run.run_id, from_index, from_index + count + 1),  # one more, to resolve a boundary at the end
            ).fetchall()
            records = (HistoryRecord.from_bytes(bytes(raw)) for (raw,) in rows)
            points = list(
                itertools.islice(
                    decode(records, charge_range=run.charge_range_raw, previous=previous, totals=totals), count
                )
            )
            self._remember(run.run_id, from_index + len(points), totals)
        start_time = (run.started_ns or 0) / 1e9
        return [
            to_data_point(point, from_index + offset, start_time, run.step_positions)
            for offset, point in enumerate(points)
        ]

    def _totals_at(self, db: sqlite3.Connection, run: RunEntry, index: int) -> RunningTotals:
        """Totals positioned before record `index`, cached or recomputed. Call with the lock held."""
        cached = self._cursors.get((run.run_id, index))
        if cached is not None:
            self._cursors.move_to_end((run.run_id, index))
            return copy.deepcopy(cached)
        totals = RunningTotals(run.charge_range_raw)
        if index:
            cursor = db.execute(
                "SELECT raw FROM records WHERE run_id=? AND record_index<? ORDER BY record_index", (run.run_id, index)
            )
            for batch in iter(lambda: cursor.fetchmany(4096), []):
                for (raw,) in batch:
                    totals.update(HistoryRecord.from_bytes(bytes(raw)))
        return totals

    def _remember(self, run_id: str, index: int, totals: RunningTotals) -> None:
        """Cache totals positioned before record `index`. Call with the lock held."""
        self._cursors[(run_id, index)] = copy.deepcopy(totals)
        self._cursors.move_to_end((run_id, index))
        while len(self._cursors) > MAXIMAL_CURSORS:
            self._cursors.popitem(last=False)

    def _forget(self, run_id: str) -> None:
        with self._lock:
            self._numbering.pop(run_id, None)
            for key in [key for key in self._cursors if key[0] == run_id]:
                del self._cursors[key]


def _migrate_from_1(db: sqlite3.Connection) -> None:
    """Number the records of schema 1, which were numbered by sequence on every read, once and for good."""
    with db:
        db.execute("ALTER TABLE runs ADD COLUMN sample_identifier TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE records ADD COLUMN record_index INTEGER")
        db.execute(
            "UPDATE records SET record_index = numbered.position FROM ("
            "SELECT run_id, sequence, row_number() OVER (PARTITION BY run_id ORDER BY sequence) - 1 AS position "
            "FROM records) AS numbered "
            "WHERE records.run_id = numbered.run_id AND records.sequence = numbered.sequence"
        )
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def _run_from_row(row: sqlite3.Row | tuple[object, ...]) -> RunEntry:
    (run_id, unit, channel, sample_name, nominal_capacity, kind, protocol, positions, stopped) = row[:9]
    test_id, started_ns, charge_range, sample_identifier = row[9:13]
    return RunEntry(
        run_id=str(run_id),
        unit=int(str(unit)),
        channel=int(str(channel)),
        sample_name=str(sample_name),
        nominal_capacity=float(str(nominal_capacity)),
        kind=ProtocolKind(kind),
        protocol=bytes(protocol) if isinstance(protocol, bytes | memoryview) else b"",
        step_positions={int(key): value for key, value in json.loads(str(positions)).items()},
        sample_identifier=str(sample_identifier),
        stopped=bool(stopped),
        test_id=None if test_id is None else int(str(test_id)),
        started_ns=None if started_ns is None else int(str(started_ns)),
        charge_range_raw=None if charge_range is None else int(str(charge_range)),
    )


__all__ = ["FILENAME", "NewareStore", "ProtocolKind", "RunEntry"]
