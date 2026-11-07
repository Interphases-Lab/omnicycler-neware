# Changelog

All notable changes to this package. The package follows semantic versioning; each feature's `version` moves independently (see the best-practices guide).

## 0.1.0 – 2026-11-07

First version.

- `create_app` serves the OmniCycler standard features (omnicycler-features 0.1.0, commit `a845361`) for a Neware BTS82 through neware8, in simulation mode by default.
- `NewareBackend`:
  - Converts aurora-unicycler protocols with aurora-unicycler's Neware exporter and compiles them with neware8. Safety limits the protocol leaves unset are filled from the channel ratings, and C-rates become rounded absolute currents.
  - Pauses with the native Stop, resumes with Continue, and stops with Stop followed by Clear Flag.
  - Numbers records from zero without gaps, and reports capacity and energy since the start of the run.
  - Stores runs and their history in its own SQLite database, as neware8's history sink: history is acknowledged to the controller only after it was committed, resent batches are deduplicated, and run IDs, samples and protocols survive restarts. `ClearChannel` deletes the run's data.
- Brand features, all `v1.0`, originator `se.uu.interphaseslab`, category `cycling.neware`:
  - `NewareProtocolController`: native BTS Step Files
  - `NewareControllerProvider`: controller and unit identity
  - `NewareSettingsService`: upload interval and clock
- `SimulationController` switches between the real controller and neware8's simulated controller.
- `NewareClient`: the OmniCycler client with the brand features.
- Decision records for the waived rules in `docs/decisions/`.
