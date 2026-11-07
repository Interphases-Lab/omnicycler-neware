import pytest

from omnicycler.neware import NewareConfig, create_app

pytest_plugins = ["omnicycler.features.testing.plugin"]


@pytest.fixture
def omnicycler_app_factory():
    return create_app


@pytest.fixture
def omnicycler_config(tmp_path) -> NewareConfig:
    return NewareConfig(
        simulation_mode=True,
        storage_directory=str(tmp_path / "neware-data"),
        simulation_time_scale=3600.0,
        simulation_status_period=0.05,
        status_interval=0.1,
    )


@pytest.fixture
def omnicycler_run_timeout() -> float:
    return 30.0
