"""
Errors of the Neware device layer.

`ChannelsNotIdleError` and `SettingRejectedError` are declared on the brand
settings feature, so clients receive them as Defined Execution Errors.
`NativeProtocolError` is turned into a validation error on the `Protocol`
parameter.
"""


class ChannelsNotIdleError(Exception):
    """
    A controller-wide setting needs every channel finished and free of alarms.

    Wait until every test has ended, and clear faulted channels with
    `ChannelController.ClearChannel`, then retry.
    """


class SettingRejectedError(Exception):
    """
    The controller explicitly rejected a setting; nothing was changed.

    Check the value and the controller's state, then retry.
    """


class NativeProtocolError(ValueError):
    """The Neware step file cannot be compiled for this channel."""


__all__ = ["ChannelsNotIdleError", "NativeProtocolError", "SettingRejectedError"]
