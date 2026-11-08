# 0003 StartNativeProtocol runs in PARALLEL mode

- **Status:** Accepted, 2026-11-07
- **Rule waived:** `op-execution-mode-by-repeatability` (`SINGLE` for every non-idempotent command).

## Context

omnicycler-features decision 0004 makes the per-channel standard commands `PARALLEL`. An execution mode applies to the whole command, so `SINGLE` would reject a start on channel 2 while channel 1 is still starting. That decision's scope names only the standard commands. `NewareProtocolController.StartNativeProtocol` is the same kind of per-channel start.

## Decision

`StartNativeProtocol` uses `PARALLEL`. `NewareBackend.start_native_protocol` goes through `CyclerBackend.start_run`, so it takes the same per-channel lock and makes the same checks as the standard `StartProtocol`:

- A start of another run on a busy channel raises `ChannelBusyError`.
- A start on a channel holding an ended run raises `ChannelNotClearedError`.
- A repeated start of the run the channel holds succeeds without effect, and a `RunId` held by another channel raises `RunIdInUseError`.

neware8 serializes the device exchanges itself.

## Scope

`StartNativeProtocol` only. `SetUploadInterval` and `SynchronizeClock` act on the whole controller and are `QUEUED`, as the guide prescribes for idempotent setters.
