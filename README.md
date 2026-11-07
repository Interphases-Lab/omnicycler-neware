# omnicycler-neware

The OmniCycler SiLA 2 server for Neware BTS82 battery cyclers. It implements the shared OmniCycler interface ([omnicycler-features](https://github.com/Interphases-Lab/omnicycler-features)) on top of [neware8](https://github.com/Interphases-Lab/neware8), our reverse-engineered native driver. Any OmniCycler client can therefore run aurora-unicycler protocols on a Neware cycler, follow the channels, and export the data as Battery Data Format, exactly as on every other brand. Three Neware brand features add what the standard cannot express.

| Part | Module |
| --- | --- |
| Server entry point | `omnicycler.neware:create_app` |
| Configuration | `omnicycler.neware.config.NewareConfig` |
| `CyclerBackend` adapter | `omnicycler.neware.backend` |
| Device layer (neware8, Neware vocabulary) and run store | `omnicycler.neware.io` |
| Brand features | `omnicycler.neware.features` |
| Typed client with the brand features | `omnicycler.neware.client.NewareClient` |

## Status

- The server passes the OmniCycler conformance suite in simulation mode, as well as its own protocol-conversion, state-mapping, client, contract and typing tests.
- **It has not been run against a real cycler yet.** neware8 itself has been tested on hardware only on our installation: a BTS82 with ten units of eight channels, rated 5 V / 10 mA, on native TCP port 8001, with a current scale of 10000. The server's defaults describe the first unit of that installation. Supervise the first real-mode runs, and read neware8's README before connecting a different model, range or firmware.
- neware8 is pinned to commit `7f71d18` of [Interphases-Lab/neware8](https://github.com/Interphases-Lab/neware8) (the `omnicycler-support` work: a driver that keeps no data, with a simulated controller; this server stores the history itself).

## Running the server

```sh
uv sync --locked
uv run config create --app omnicycler.neware:create_app       # writes config.json (never commit it)
uv run connector start --app omnicycler.neware:create_app --config-path config.json
```

The server starts in **simulation mode**, with a simulated BTS82 controller (see below). For the real cycler, set `simulation_mode` to `false` in the config, or call `SimulationController.StartRealMode` at runtime. In real mode the server listens on `listen_host:listen_port`, and the controller connects to it. Configure the controller's host endpoint first, using the established site procedure. The server starts and serves even while no controller is connected: every channel then reports `unavailable`.

On Windows, run with `PYTHONUTF8=1`. Otherwise the CDK fails while logging an error to a cp1252 console and turns every defined error into an undefined one.

### Configuration

Besides the CDK's `sila_server` section (use TLS outside localhost):

| Field | Default | Meaning |
| --- | --- | --- |
| `simulation_mode` | `true` | Start with the simulated controller |
| `listen_host`, `listen_port` | `0.0.0.0`, `8001` | The address the controller connects to, as configured on the controller |
| `controller_host` | `127.0.0.1` | The controller's IP address; other peers are refused |
| `storage_directory` | `neware-data` | Where the server keeps runs and their history (`omnicycler-neware.sqlite`). Simulation mode uses `simulation/` inside it |
| `channels` | unit 1, channels 1–8, physical IDs 0–7, 5 V, 0.01 A, scale 10000 | Each installed main channel: `unit`, `channel`, `physical_id` (from the installation's channel map), `voltage_rating`, `current_rating`, `current_scale`, optional `charge_range_raw` |
| `model` | `BTS82` | Reported as `CyclerInformationProvider.Model` |
| `upload_interval` | `5` | The controller's current status upload interval, in seconds. neware8 judges status freshness by it, so it must match the controller |
| `start_timeout` | `30` | How long a start waits for the controller to report the new test |
| `status_interval` | `1` | Polling period for status subscribers and monitors |
| `simulation_time_scale`, `simulation_status_period` | `60`, `0.5` | Speed and status cadence of the simulated controller |

The OmniCycler channel number is `(unit - 1) * 8 + channel`. Channels and physical IDs must be unique.

## How the standard interface maps onto the BTS82

**Protocols.** An aurora-unicycler protocol is merged with the sample and checked by omnicycler-features, then converted into a BTS Step File by aurora-unicycler's own Neware exporter. neware8 compiles that file for the channel, offline, during `ValidateProtocol` and `StartProtocol`. neware8 accepts only a protected subset of step files, so the conversion adapts the protocol as follows and reports every adaptation as a `ValidateProtocol` warning:

- Safety limits the protocol leaves unset are filled from the channel's ratings: 0 V to the rated voltage, and the rated current in both directions.
- C-rates become absolute currents. Every value is rounded to the native resolution: 0.1 mV, 1 ms, and one current unit, which is 0.1 µA at scale 10000.
- These are rejected as `Protocol` validation errors:
  - a step without `until_time_s`
  - a constant-voltage step that does not directly follow a constant-current step ending at its voltage, or that has no cutoff current
  - a current at or above the channel's current protection
  - voltage scans and impedance spectroscopy

`SupportedStepTypes` is therefore open-circuit voltage, constant current and constant voltage.

**States.** The BTS82 has no pause command. This server pauses with the native Stop, resumes with Continue, and stops with Stop followed by Clear Flag, remembering that a client stopped the run.

| Native state | Run started by this server | Otherwise |
| --- | --- | --- |
| finish | `finished` (`stopped` if a client stopped it, `faulted` if it shows an alarm) | `idle` |
| running, wait start/timeout, synchronous control | `running` | `unavailable` |
| stop, pause, offline pause, beep, reserved pause | `paused` | `unavailable` |
| protect, finish protect, fixture states, unknown | `faulted` | `unavailable` |
| not reported, stale, or controller disconnected | `unavailable` | `unavailable` |

`FaultReason` is the alarm's description from the manufacturer's catalogue, followed by its code. `ClearChannel` sends Clear Flag to a protected channel and deletes the run with its records from the server's store; the controller's own history is untouched. Because the run is gone, a cleared channel stays `idle` after a server restart, unlike on the reference simulator.

**Data.** neware8 is a driver: it hands every history batch to the server's run store (`io/store.py`) and acknowledges it to the controller only after the store committed it durably. The store is one SQLite database holding each run's description (run ID, sample, protocol, step mapping, stopped flag), its TestID, and its main-channel records, deduplicated by sequence, together with the controller's resend position. Records are decoded with neware8's history helpers, which already give BDF units: V, A (positive when charging), Ah, Wh, s.

| Field | Source |
| --- | --- |
| `RecordIndex` | Numbers the stored records from zero without gaps, in sequence order |
| `UnixTime` | Host receipt time of the test start plus test time, because the controller's calendar has no established time zone |
| `ChargingCapacity`, `DischargingCapacity`, `ChargingEnergy`, `DischargingEnergy` | The device's step counters accumulated since the start (neware8's `RunningTotals`); NaN after a history gap |
| `StepCount` | The number of step executions observed |
| `ProtocolStep` | The unicycler method position of the executing native step |
| Temperatures, pressures, resistances, impedance | NaN; `MeasuredQuantities` is empty |

`ExportData` is the standard export from omnicycler-features, so a Neware run exports exactly like any other brand.

## Neware brand features

Per omnicycler-features decision 0001, these are separate features with originator `se.uu.interphaseslab` and category `cycling.neware`. The standard features are unchanged.

| Feature | Endpoints |
| --- | --- |
| `NewareProtocolController` | `StartNativeProtocol(Channel, Protocol, Sample)`, `ValidateNativeProtocol(Channel, Protocol, Sample) → NativeProtocolSummary` |
| `NewareControllerProvider` | `ControllerIdentifier`, `ClockSettingRequested`, `Units`, `GetUnitInformation(Unit) → UnitInformation` |
| `NewareSettingsService` | `UploadInterval` (observable), `SetUploadInterval(Interval)`, `SynchronizeClock()` |

`StartNativeProtocol` takes a BTS Step File (XML) within neware8's subset. Its run follows the standard lifecycle, with `ProtocolFormat` `native`. `SynchronizeClock` sets the controller clock to the host's local time, and needs every channel finished and alarm-free (`ChannelsNotIdleError`). TestID initialization, firmware and calibration are not exposed.

```python
from omnicycler.features.types import Sample
from omnicycler.neware.client import ClientConfig, NewareClient

async with NewareClient.connect(ClientConfig(hostname="cycler-pc.local", port=50052, root_certificates=ca)) as cycler:
    summary = await cycler.protocols.validate_native_protocol(1, step_file, Sample(name="NMC-042", nominal_capacity=0.0045))
    await cycler.protocols.start_native_protocol(1, step_file, Sample(name="NMC-042", nominal_capacity=0.0045))
    print(await cycler.controller.get_unit_information(1))
```

`NewareClient` is an `OmniCyclerClient`, so `cycler.channels`, `cycler.information` and `cycler.measurements` work as documented in omnicycler-features. Code that needs only the standard features can use `OmniCyclerClient` against this server unchanged.

## Simulation mode

Simulation happens at the native protocol level. The server's own neware8 client listens on a local port, and `neware8.simulator.SimulatedController` connects to it like the real controller. The simulator executes each downloaded program on an equivalent-circuit cell (5 mAh by default), with protections, alarms, recording intervals, Stop/Continue/Clear Flag and history that survives reconnects. Every command therefore goes through the same neware8 client, native frames and run store as in real mode. Simulated data lives in `storage_directory/simulation`.

## Known limitations

- Steps need `until_time_s`. CV only works as the second half of a CC→CV pair, with a cutoff current. There are no voltage scans and no impedance spectroscopy.
- aurora-unicycler's Neware exporter writes `safety.max_capacity_mAh` as a capacity protection that the BTS82 applies to each step, not to the whole run.
- While any channel shows a protection alarm, neware8 refuses to start other channels. Clear faulted channels promptly. A cleared channel keeps reporting its last alarm code until its next start, so `SynchronizeClock` is refused until then.
- `ClearChannel` deletes the run's data from the server. Export it first if you need it.
- Tests started outside this server, for example in the BTS software, show as `unavailable`, and their data is not recorded.
- If late history fills an earlier gap in a run, the record indices after the gap shift by the number of records filled in.
- neware8's limits apply: its protocol knowledge comes from captures and static analysis, and not every operation has been exercised on hardware.

## Development

```sh
uv sync --locked
uv run ruff format --check
uv run ruff check
uv run ty check
uv run lint-imports
uv run pytest                       # hardware tests excluded
uv build
```

| Tests | What they prove |
| --- | --- |
| `tests/test_conformance.py` | The OmniCycler conformance suite, in simulation mode |
| `tests/io/` | Protocol conversion, the state table, the run store (binding, registration, deduplication, conflicts, checkpoint, restart, gap-free indices and resumable totals), data-point conversion |
| `tests/client/` | Every brand client method and declared error against the in-process server; `test_typing.py` is checked by ty |
| `tests/contract/` | The brand client against the live brand feature definitions |
| `tests/test_config.py`, `tests/test_real_mode.py` | Configuration validation; real mode starts and serves without a controller |
| `tests/hardware/` | Read-only checks against a real controller; opt-in (`-m hardware`), only with approval |

Native protocol framing, recipes, history decoding and the simulator are tested in neware8.

Departures from the UniteLabs review checklist and our best-practices guide are recorded in [docs/decisions/](docs/decisions/README.md). The decisions of [omnicycler-features](https://github.com/Interphases-Lab/omnicycler-features/tree/main/docs/decisions) apply as well.
