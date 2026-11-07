# 0004 Brand client uses the OmniCycler client helpers

- **Status:** Accepted, 2026-11-07
- **Rule waived:** client rule 1 as the guide lays it out: all `Any`-typed library access lives in the package's own `client/_base.py`.

## Context

omnicycler-features decision 0006 lets brand repositories extend `OmniCyclerClient` with clients for their brand features. The conversion and error helpers (`from_wire`, `to_wire`, `translate_errors`, `error_map`, `response`) live in `omnicycler.features.client._base`, which is a private module.

## Decision

The brand feature clients in `omnicycler.neware.client` import those helpers rather than copying them, so both clients decode the wire and translate errors identically. There is no `client/_base.py` here.

All `Any`-typed access to `sila.client` stays inside the per-feature client modules. Public methods return shared types only, and `tests/client/test_typing.py` checks this with ty.

## Consequences

The brand client depends on a private module of a pinned omnicycler-features version. Any upgrade of that pin must rerun the client, contract and typing tests. Making the helpers public in omnicycler-features would remove this waiver.
