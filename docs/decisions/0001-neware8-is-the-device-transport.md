# 0001 neware8 is the device transport

- **Status:** Accepted, 2026-11-07
- **Rules waived:**
  - the `io/` layer as a `unitelabs.bus.Protocol` subclass
  - `test-always-include-simulation-mode` as written: swap the transport for `create_mock_connection`
  - `test-simulation-stubs-in-io`: request-bytes to response-bytes stubs
  - `test-protocol-with-stubbed-responses`: Omnibus fixtures

## Context

The BTS82 protocol is reverse engineered and maintained in neware8, which handles everything the device demands:

- The controller connects to the host, not the other way round.
- History must be committed durably before it is acknowledged, and resent from a saved position after every connect.
- Writes must never be replayed.
- A start is a sequence of seven checked exchanges.

neware8 has more than 150 tests of its own. Re-implementing the framing on `unitelabs.bus` would duplicate that work and split the protocol knowledge across two repositories.

## Decision

- `io/` wraps one `neware8.Client` (`io/controller.py`) and stays in neware8's vocabulary. It holds all business logic: protocol conversion, state mapping, and the run store (`io/store.py`), which is neware8's `HistorySink` and keeps the runs and their records. `unitelabs-bus` is not a dependency.
- Simulation happens at neware8's native protocol level. In simulation mode, the server's own neware8 client listens on a local port, and `neware8.simulator.SimulatedController` connects to it over TCP. The simulator speaks the native frames and executes the downloaded programs. Everything from the features down to the run store and neware8's framing is the code that runs in real mode. `io/simulation.py` only configures the simulator.
- Byte-level protocol tests live in neware8. This repository tests the `io/` logic directly, and the whole stack through the typed client.

## Consequences

- The intent of the simulation rules is kept: simulate below the features and exercise the real interface. It also covers more of the stack than byte stubs would.
- neware8 is pinned. A protocol change is made and tested in neware8, then picked up here by updating the pin.
