# Changelog

All notable changes to this package. The package follows semantic versioning; each feature's `version` moves independently (see the best-practices guide).

## Unreleased

- The simulated controller outlives a server restart within the process, as the real controller does, so the conformance kit's restart tests apply.
- omnicycler-features commit `bd2792c`, with the conformance kit's restart tests and the UTF-8 console; `PYTHONUTF8=1` is no longer needed.

## 0.1.0 – 2026-11-07

First version.

- `create_app` serves the OmniCycler standard features (omnicycler-features 0.1.0, commit `99dd45e`) for a Neware BTS82 through neware8, in simulation mode by default.
- `NewareBackend`:
  - Converts aurora-unicycler protocols with aurora-unicycler's Neware exporter and compiles them with neware8. Current safety limits the protocol leaves unset are filled from the channel rating, and C-rates become rounded absolute currents.
  - Pauses with the native Stop, resumes with Continue, and stops with Stop followed by Clear Flag.
  - Numbers records from zero without gaps, once, as they arrive, so an index never changes; late history is kept but not served. Reports capacity and energy since the start of the run.
  - Reports each channel's run by the client's `RunId`, also while the controller is disconnected, when its data stays readable.
  - Stores runs and their history in its own SQLite database, as neware8's history sink: history is acknowledged to the controller only after it was committed, resent batches are deduplicated, and run IDs, samples and protocols survive restarts. `ClearChannel` deletes the run with its data. Stores of schema 1 are migrated on open.
- Brand features, all `v1.0`, originator `se.uu.interphaseslab`, category `cycling.neware`:
  - `NewareProtocolController`: native BTS Step Files, started with a client-chosen `RunId`
  - `NewareControllerProvider`: controller and unit identity
  - `NewareSettingsService`: upload interval and clock
- `SimulationController` switches between the real controller and neware8's simulated controller.
- `NewareClient`: the OmniCycler client with the brand features.
- Decision records for the waived rules in `docs/decisions/`.
