from datetime import datetime, timezone

import pytest

from dendroflow.ingestion.conflicts import (
    ObservationConflictError,
    deduplicate_observations,
    values_equal,
)
from dendroflow.ingestion.models import NormalizedObservation


def observation(*, value=2.5, interface_id=1, source_row_number=2):
    return NormalizedObservation(
        location_id=10,
        variable_id=20,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        value=value,
        interface_id=interface_id,
        source_row_number=source_row_number,
    )


def test_equal_repeated_identity_keeps_first_source_line():
    first = observation(source_row_number=2)
    repeated = observation(source_row_number=8)

    unique, repeated_count = deduplicate_observations((first, repeated))

    assert unique == (first,)
    assert repeated_count == 1


@pytest.mark.parametrize(
    ("second", "message"),
    [
        (observation(value=3.5, source_row_number=8), "normalized values"),
        (observation(interface_id=2, source_row_number=8), "interfaces"),
    ],
)
def test_conflicting_repeated_identity_is_rejected(second, message):
    with pytest.raises(ObservationConflictError, match=message):
        deduplicate_observations((observation(), second))


def test_normalized_nan_values_compare_equal():
    assert values_equal(float("nan"), float("nan"))
    assert not values_equal(float("nan"), 1.0)
