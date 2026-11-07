"""
Typed async client for the OmniCycler Neware server.

`NewareClient` is `OmniCyclerClient` plus the Neware brand features:

    async with NewareClient.connect(ClientConfig(hostname="cycler-pc.local", port=50052, ...)) as cycler:
        summary = await cycler.protocols.validate_native_protocol(1, step_file, sample)
        await cycler.protocols.start_native_protocol(1, step_file, sample)
        await cycler.channels.stop_protocol(1)  # the standard features work as on every OmniCycler server

Use `OmniCyclerClient` from `omnicycler.features.client` when the brand features are not needed; it works with this
server unchanged.
"""

from omnicycler.features.client import ClientConfig, OmniCyclerClient
from omnicycler.features.client._base import require_feature
from sila.client import Client

from . import neware_controller_provider, neware_protocol_controller, neware_settings_service
from .neware_controller_provider import NewareControllerProviderClient
from .neware_protocol_controller import NewareProtocolControllerClient
from .neware_settings_service import NewareSettingsServiceClient

FEATURES = (neware_protocol_controller.FEATURE, neware_controller_provider.FEATURE, neware_settings_service.FEATURE)
"""The fully qualified identifiers of the Neware brand features this client requires."""


class NewareClient(OmniCyclerClient):
    """
    Typed client for the OmniCycler Neware server. Create it with `NewareClient.connect(config)`.

    Attributes:
      protocols: Native Neware step files.
      controller: The controller and its lower units.
      settings: Controller-wide settings.
    """

    def __init__(self, client: Client) -> None:
        super().__init__(client)
        self.protocols = NewareProtocolControllerClient(require_feature(client, neware_protocol_controller.FEATURE))
        self.controller = NewareControllerProviderClient(require_feature(client, neware_controller_provider.FEATURE))
        self.settings = NewareSettingsServiceClient(require_feature(client, neware_settings_service.FEATURE))


__all__ = [
    "FEATURES",
    "ClientConfig",
    "NewareClient",
    "NewareControllerProviderClient",
    "NewareProtocolControllerClient",
    "NewareSettingsServiceClient",
]
