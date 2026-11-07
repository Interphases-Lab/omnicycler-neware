"""
OmniCycler SiLA 2 server for Neware BTS82 battery cyclers.

Run it with `uv run connector start --app omnicycler.neware:create_app --config-path config.json`. Importing this
package opens no ports, connections or event loops.
"""

import collections.abc

from omnicycler.features.server import register_standard_features
from unitelabs.cdk import Connector

from .backend import NewareBackend
from .config import NewareChannelConfig, NewareConfig
from .features import (
    NewareControllerProvider,
    NewareProtocolController,
    NewareSettingsService,
    SimulationController,
)


async def create_app(config: NewareConfig) -> collections.abc.AsyncGenerator[Connector]:
    """Create the Neware connector: listen for the controller, then register every feature."""
    app = Connector(config)
    backend = NewareBackend.from_config(config)
    async with backend:  # listens only; never touches running tests
        register_standard_features(app, backend, status_interval=config.status_interval)
        app.register(NewareProtocolController(backend))
        app.register(NewareControllerProvider(backend))
        app.register(NewareSettingsService(backend, poll_interval=config.status_interval))
        app.register(SimulationController(backend))
        yield app


__all__ = ["NewareChannelConfig", "NewareConfig", "create_app"]
