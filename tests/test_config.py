import pytest
from unitelabs.cdk import ConfigurationError

from omnicycler.neware import NewareChannelConfig, NewareConfig

OVERRIDE = {"physical_id": 7, "voltage_rating": 5.0, "current_rating": 0.01, "current_scale": 10000}


def test_defaults_are_simulation_with_channels_from_the_controller():
    config = NewareConfig()
    assert config.simulation_mode is True
    assert config.channels == []
    assert config.simulation_units == 1


def test_channel_overrides_load_from_a_config_file_and_number_across_units():
    config = NewareConfig.validate(
        {
            "channels": [
                {"unit": 1, "channel": 8, **OVERRIDE},
                {"unit": 2, "channel": 1, **OVERRIDE, "physical_id": 8},
            ]
        }
    )
    assert all(isinstance(channel, NewareChannelConfig) for channel in config.channels)
    assert [channel.number for channel in config.channels] == [8, 9]


@pytest.mark.parametrize(
    "values",
    [
        {"channels": [{"unit": 1, "channel": 1, **OVERRIDE}, {"unit": 1, "channel": 2, **OVERRIDE}]},
        {"channels": [{"unit": 1, "channel": 1, **OVERRIDE}, {"unit": 1, "channel": 1, **OVERRIDE, "physical_id": 1}]},
        {"channels": [{"unit": 1, "channel": 1, "physical_id": 0}]},  # an override gives every value
        {"controller_host": "cycler.local"},
    ],
)
def test_invalid_configurations_are_rejected(values):
    with pytest.raises((ConfigurationError, ValueError, TypeError)):
        NewareConfig.validate(values)
