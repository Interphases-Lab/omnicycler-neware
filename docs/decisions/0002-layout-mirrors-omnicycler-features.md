# 0002 Layout mirrors omnicycler-features

- **Status:** Accepted, 2026-11-07
- **Rule waived:** "Start every package from the Connector Factory cookiecutter".

## Context

The Connector Factory scaffolds a `unitelabs.bus` device connector, without a client. This server differs in three ways:

- It has no `unitelabs.bus` protocol (0001).
- It shares its standard features and client with omnicycler-features.
- It is one of several brand servers that should look alike.

## Decision

The repository was created with `uv` and mirrors omnicycler-features:

- the same `pyproject.toml` tool configuration
- the `omnicycler.<name>` namespace
- `config.py` and `types.py`
- `io/` with `units.py`, `errors.py` and `simulation.py`
- `features/` and `client/`
- the test layers of the guide

The CDK's `config` and `connector` commands work as they do with a Factory project.

## Consequences

Brand servers stay uniform with one another. Changes the Factory makes to its template are not picked up automatically, so review them when upgrading the CDK.
