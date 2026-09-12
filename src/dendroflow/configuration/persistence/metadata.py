from ..plan import PlanAction, ResolvedPlanItem
from .context import ApplyContext
from .models import ApplyItemResult

_METADATA_RESOURCE_TYPES = frozenset(
    {
        "site",
        "location_type",
        "sensor_type",
        "variable",
        "sensor_model",
        "sensor",
        "location",
        "location_label",
        "deployment",
    }
)


def create_metadata_item(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    """Persist one resolved METADATA CREATE item."""

    if item.action != PlanAction.CREATE:
        raise ValueError(
            "METADATA create persistence requires CREATE action"
        )

    if item.resource_type not in _METADATA_RESOURCE_TYPES:
        raise ValueError(
            "unsupported METADATA resource type: "
            f"{item.resource_type}"
        )

    raise NotImplementedError(
        "METADATA CREATE writer not implemented for "
        f"{item.resource_type}"
    )

