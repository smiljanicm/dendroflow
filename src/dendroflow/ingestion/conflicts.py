import math
from datetime import datetime

from .models import NormalizedObservation


class ObservationConflictError(ValueError):
    """Raised when an observation would change established RAW data."""

    def __init__(
        self,
        message: str,
        *,
        source_line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.source_line = source_line


def observation_identity(
    observation: NormalizedObservation,
) -> tuple[int, int, datetime]:
    return (
        observation.location_id,
        observation.variable_id,
        observation.timestamp,
    )


def values_equal(left: float, right: float) -> bool:
    """Compare normalized numeric values using the RAW equality contract."""

    return left == right or (math.isnan(left) and math.isnan(right))


def deduplicate_observations(
    observations: tuple[NormalizedObservation, ...],
) -> tuple[tuple[NormalizedObservation, ...], int]:
    """Collapse equal repeated identities, retaining their first source row."""

    unique: dict[tuple[int, int, datetime], NormalizedObservation] = {}
    repeated = 0

    for incoming in observations:
        identity = observation_identity(incoming)
        existing = unique.get(identity)
        if existing is None:
            unique[identity] = incoming
            continue

        repeated += 1
        if existing.interface_id != incoming.interface_id:
            reason = "different interfaces"
        elif not values_equal(existing.value, incoming.value):
            reason = "different normalized values"
        else:
            continue

        raise ObservationConflictError(
            "Repeated observation identity has "
            f"{reason}: identity={identity}, "
            f"first_source_line={existing.source_row_number}, "
            f"incoming_source_line={incoming.source_row_number}",
            source_line=incoming.source_row_number,
        )

    return tuple(unique.values()), repeated
