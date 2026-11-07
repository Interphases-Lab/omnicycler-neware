"""Feature metadata of the Neware brand features, shared by the features and the typed client."""

from omnicycler.features import ORIGINATOR

CATEGORY = "cycling.neware"
"""The category of every Neware brand feature."""


def feature_identifier(name: str, major: int = 1) -> str:
    """Return the fully qualified identifier of a Neware brand feature."""
    return f"{ORIGINATOR}/{CATEGORY}/{name}/v{major}"


__all__ = ["CATEGORY", "ORIGINATOR", "feature_identifier"]
