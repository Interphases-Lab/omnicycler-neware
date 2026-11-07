import pytest
from unitelabs.cdk import ConfigurationError

from omnicycler.neware import NewareChannelConfig, NewareConfig


def test_defaults_are_simulation_with_one_unit_of_eight_channels():
    config = NewareConfig()
    assert config.simulation_mode is True
    assert [channel.number for channel in config.channels] == list(range(1, 9))


def test_channels_load_from_a_config_file_and_number_across_units():
    config = NewareConfig.validate(
        {"channels": [{"unit": 1, "channel": 8, "physical_id": 7}, {"unit": 2, "channel": 1, "physical_id": 8}]}
    )
    assert all(isinstance(channel, NewareChannelConfig) for channel in config.channels)
    assert [channel.number for channel in config.channels] == [8, 9]


@pytest.mark.parametrize(
    "values",
    [
        {"channels": [{"unit": 1, "channel": 1, "physical_id": 0}, {"unit": 1, "channel": 2, "physical_id": 0}]},
        {"channels": [{"unit": 1, "channel": 1, "physical_id": 0}, {"unit": 1, "channel": 1, "physical_id": 1}]},
        {"channels": []},
        {"controller_host": "cycler.local"},
    ],
)
def test_invalid_configurations_are_rejected(values):
    with pytest.raises((ConfigurationError, ValueError)):
        NewareConfig.validate(values)
