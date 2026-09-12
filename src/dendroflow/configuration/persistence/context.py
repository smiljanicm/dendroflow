from dataclasses import dataclass, field

from ..plan import ExistingRef, PlannedRef, ResourceRef
from .models import ApplyError, ApplyErrorCode


@dataclass(frozen=True)
class AppliedResource:
    resource_type: str
    database_id: int


@dataclass
class ApplyContext:
    _planned_ids: dict[str, AppliedResource] = field(
        default_factory=dict
    )

    def register(
        self,
        *,
        plan_id: str,
        resource_type: str,
        database_id: int,
    ) -> None:
        """Register the database ID created for a planned resource."""

        if plan_id in self._planned_ids:
            raise ValueError(
                f"plan_id already registered: {plan_id}"
            )

        if database_id <= 0:
            raise ValueError(
                "database_id must be positive"
            )

        self._planned_ids[plan_id] = AppliedResource(
            resource_type=resource_type,
            database_id=database_id,
        )

    def resolve(
        self,
        reference: ResourceRef,
    ) -> int:
        """Resolve a resource reference to its database ID."""

        if isinstance(reference, ExistingRef):
            return reference.database_id

        if isinstance(reference, PlannedRef):
            resource = self._planned_ids.get(
                reference.plan_id
            )

            if (
                resource is None
                or resource.resource_type
                != reference.resource_type
            ):
                raise ApplyError(
                    ApplyErrorCode.UNRESOLVED_PLANNED_REF,
                    (
                        "planned reference is not available "
                        f"for apply: {reference.resource_type} "
                        f"{reference.plan_id}"
                    ),
                )

            return resource.database_id

        raise TypeError(
            "unsupported resource reference type: "
            f"{type(reference).__name__}"
        )


