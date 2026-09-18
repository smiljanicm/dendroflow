from dataclasses import dataclass, replace

from ..plan import ResolvedPlan, ResolvedPlanItem
from .preparation import MetadataPreparation, prepare_metadata_plan
from .raw_preparation import RawPreparation, prepare_raw_plan


@dataclass(frozen=True)
class CombinedPreparation:
    """Prepared stages for METADATA-before-RAW execution.

    Preparation does not execute operations, register generated IDs,
    or establish that either stage committed.
    """

    metadata: MetadataPreparation
    raw: RawPreparation

    @property
    def items(self) -> tuple[ResolvedPlanItem, ...]:
        return self.metadata.items + self.raw.items

    @property
    def requires_writes(self) -> bool:
        return (
            self.metadata.requires_writes
            or self.raw.requires_writes
        )


def prepare_plan(
    plan: ResolvedPlan,
    *,
    confirm_identity_changes: bool = False,
) -> CombinedPreparation:
    """Prepare both stages without database access.

    RAW preparation checks full-plan preflight, global plan-ID
    uniqueness, and cross-stage deployment targets.

    METADATA preparation then validates the METADATA operations and
    their dependencies using a copy with RAW items removed.

    Database constraints and execution-time validation can still fail
    after preparation succeeds.
    """
    raw = prepare_raw_plan(
        plan,
        confirm_identity_changes=confirm_identity_changes,
        allow_metadata_dependencies=True,
    )

    metadata = prepare_metadata_plan(
        replace(plan, raw_items=()),
        confirm_identity_changes=confirm_identity_changes,
    )

    return CombinedPreparation(
        metadata=metadata,
        raw=raw,
    )
