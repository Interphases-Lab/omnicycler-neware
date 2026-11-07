# Waivers of the best-practice rules

This server follows the SiLA 2 best-practices guide and the decisions of omnicycler-features, whose records 0001–0006
apply here unchanged. The records below cover only what this repository adds. A waiver covers what its record names
and nothing else.

| # | Record | Rule waived |
| --- | --- | --- |
| 0001 | [neware8 is the device transport](0001-neware8-is-the-device-transport.md) | `unitelabs.bus` protocol layer, mock-transport simulation, byte stubs |
| 0002 | [Layout mirrors omnicycler-features](0002-layout-mirrors-omnicycler-features.md) | Start from the Connector Factory |
| 0003 | [StartNativeProtocol runs in PARALLEL mode](0003-native-start-runs-in-parallel-mode.md) | `op-execution-mode-by-repeatability` |
| 0004 | [Brand client uses the OmniCycler client helpers](0004-brand-client-uses-omnicycler-client-helpers.md) | Client rule 1 (wrapping lives in this package's `_base.py`) |
