"""Resolve generated YAML and verify the CONFIG plan against workbook intent."""

from dataclasses import dataclass

from ..plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlannedRef,
    ResolvedPlan,
    ResolvedPlanItem,
)
from ..resolution.orchestration import resolve_config
from .comparison import ComparisonStatus, WorkbookReference
from .configuration import GeneratedConfiguration
from .schema import RESOURCE_SHEETS, get_sheet_spec
from .serialization import SerializedConfiguration, serialize_configuration

_UPDATE_SECTIONS = {
    "sites": "sites",
    "location_types": "location_types",
    "sensor_types": "sensor_types",
    "variables": "variables",
    "sensor_models": "sensor_models",
    "sensors": "sensors",
    "locations": "locations",
    "deployments": "deployments",
}

_DECLARATION_SECTIONS = tuple(
    sheet
    for sheet in (
        "sites",
        "location_types",
        "sensor_types",
        "variables",
        "sensor_models",
        "sensors",
        "locations",
        "location_labels",
        "deployments",
        "files",
    )
)


class WorkbookPlanVerificationError(ValueError):
    """The live CONFIG plan does not implement the workbook comparison."""

    def __init__(self, issues: tuple[str, ...], plan: ResolvedPlan | None = None):
        self.issues = issues
        self.plan = plan
        super().__init__("; ".join(issues))


@dataclass(frozen=True)
class VerifiedWorkbookConfiguration:
    """Serialized CONFIG and the resolved plan verified against workbook intent."""

    serialized: SerializedConfiguration
    plan: ResolvedPlan


class _PlanVerifier:
    def __init__(self, generated: GeneratedConfiguration, plan: ResolvedPlan):
        self.generated = generated
        self.config = generated.config
        self.plan = plan
        self.issues: list[str] = []
        self.items_by_path: dict[str, ResolvedPlanItem] = {}
        for item in plan.items:
            if item.source_path is None:
                self.issues.append(f"plan item {item.plan_id!r} has no source path")
                continue
            if item.source_path in self.items_by_path:
                self.issues.append(f"duplicate plan source path {item.source_path!r}")
            else:
                self.items_by_path[item.source_path] = item
        self.bindings: dict[tuple[str, str], PlanBinding] = {}
        for binding in plan.bindings:
            key = (binding.resource_type, binding.alias)
            if key in self.bindings:
                self.issues.append(
                    f"duplicate plan binding for {binding.resource_type} alias {binding.alias!r}"
                )
            else:
                self.bindings[key] = binding

    def verify(self) -> tuple[str, ...]:
        for error in self.plan.errors:
            self.issues.append(f"{error.source_path}: {error.message}")
        self.verify_references()
        expected_paths = self.verify_declarations()
        expected_paths.update(self.verify_updates())
        actual_paths = set(self.items_by_path)
        for path in sorted(expected_paths - actual_paths):
            self.issues.append(f"resolved plan is missing expected operation {path}")
        for path in sorted(actual_paths - expected_paths):
            self.issues.append(f"resolved plan has unexpected operation {path}")
        return tuple(self.issues)

    def verify_references(self) -> None:
        references = self.config.references
        for spec in RESOURCE_SHEETS:
            if spec.name not in self.generated.selectors.selectors:
                continue
            section = getattr(references, spec.name)
            selectors = self.generated.selectors.selectors.get(spec.name, {})
            selector_by_alias = {selector.alias: selector for selector in selectors.values()}
            for alias in section:
                selector = selector_by_alias.get(alias)
                if selector is None:
                    self.issues.append(f"reference {spec.name}.{alias} has no verified workbook selector")
                    continue
                binding = self.bindings.get((spec.name, alias))
                expected = ExistingRef(spec.resource_type, selector.database_id)
                if binding is None:
                    self.issues.append(f"reference {spec.name}.{alias} has no resolved plan binding")
                elif binding.resource != expected:
                    self.issues.append(
                        f"reference {spec.name}.{alias} resolved to {binding.resource!r}; "
                        f"expected {expected!r}"
                    )

    def verify_declarations(self) -> set[str]:
        expected: set[str] = set()
        for section in _DECLARATION_SECTIONS:
            declarations = getattr(self.config, section)
            spec = get_sheet_spec(section)
            for index, declaration in enumerate(declarations):
                path = f"{section}[{index}]"
                expected.add(path)
                item = self.items_by_path.get(path)
                if item is None:
                    continue
                if item.resource_type != spec.resource_type:
                    self.issues.append(
                        f"{path} resolved as {item.resource_type!r}, "
                        f"expected {spec.resource_type!r}"
                    )
                if item.action not in {PlanAction.CREATE, PlanAction.REUSE}:
                    self.issues.append(f"declaration {path} resolved as {item.action.value.upper()}")
                alias = getattr(declaration, "ref", None)
                if alias is not None:
                    binding = self.bindings.get((section, alias))
                    expected_resource = self._resource_for_item(item)
                    if section == "files":
                        selectors = self.generated.selectors.selectors.get("files", {})
                        existing_selector = next(
                            (selector for selector in selectors.values() if selector.alias == alias),
                            None,
                        )
                        if existing_selector is not None:
                            expected_resource = ExistingRef("file", existing_selector.database_id)
                            if item.action != PlanAction.REUSE or item.database_id != existing_selector.database_id:
                                self.issues.append(
                                    f"{path} targets file ID {item.database_id!r}; "
                                    f"expected existing file ID {existing_selector.database_id}"
                                )
                    if binding is None:
                        self.issues.append(f"declaration {path} alias {alias!r} has no resolved binding")
                    elif binding.resource != expected_resource:
                        self.issues.append(
                            f"declaration {path} alias {alias!r} resolves to {binding.resource!r}; "
                            f"expected {expected_resource!r}"
                        )
                if section == "locations":
                    nested_path = f"{path}.initial_label"
                    expected.add(nested_path)
                elif section == "files":
                    for interface_index, _ in enumerate(declaration.interfaces):
                        expected.add(f"{path}.interfaces[{interface_index}]")
        return expected

    def verify_updates(self) -> set[str]:
        expected_paths: set[str] = set()
        for sheet, section in _UPDATE_SECTIONS.items():
            rows = [
                row
                for row in self.generated.comparison.rows[sheet]
                if row.status == ComparisonStatus.UPDATE
            ]
            updates = getattr(self.config.updates, section)
            if len(rows) != len(updates):
                self.issues.append(
                    f"updates.{section} contains {len(updates)} entries for {len(rows)} workbook changes"
                )
            for index, row in enumerate(rows):
                path = f"updates.{section}[{index}]"
                expected_paths.add(path)
                item = self.items_by_path.get(path)
                if item is None:
                    continue
                if item.action != PlanAction.UPDATE:
                    self.issues.append(f"{path} resolved as {item.action.value.upper()}, expected UPDATE")
                if item.resource_type != get_sheet_spec(sheet).resource_type:
                    self.issues.append(
                        f"{path} resolved as {item.resource_type!r}, "
                        f"expected {get_sheet_spec(sheet).resource_type!r}"
                    )
                if item.database_id != row.match.database_id:
                    self.issues.append(
                        f"{path} targets database ID {item.database_id!r}; "
                        f"expected {row.match.database_id!r}"
                    )
                self._verify_update_changes(sheet, path, row.changes, item)
        return expected_paths

    def _verify_update_changes(self, sheet, path, workbook_changes, item) -> None:
        expected = {}
        spec = get_sheet_spec(sheet)
        for change in workbook_changes:
            if change.update_field is None:
                continue
            column = next(field for field in spec.fields if field.name == change.field)
            expected[change.update_field] = (
                self._expected_value(column.target_sheet, change.before),
                self._expected_value(column.target_sheet, change.after),
            )
        actual = {change.field: (change.before, change.after) for change in item.changes}
        if set(actual) != set(expected):
            self.issues.append(
                f"{path} changes fields {sorted(actual)!r}; expected {sorted(expected)!r}"
            )
            return
        for field, expected_values in expected.items():
            if actual[field] != expected_values:
                self.issues.append(
                    f"{path}.{field} resolves from {actual[field]!r}; expected {expected_values!r}"
                )

    def _expected_value(self, target_sheet: str | None, value):
        if target_sheet is None or value is None:
            return value
        if isinstance(value, WorkbookReference):
            if value.database_id is not None:
                return ExistingRef(
                    get_sheet_spec(target_sheet).resource_type,
                    value.database_id,
                )
            alias = value.ref
        else:
            alias = value
        binding = self.bindings.get((target_sheet, alias))
        if binding is None:
            self.issues.append(f"relationship alias {target_sheet}.{alias} has no resolved binding")
            return None
        return binding.resource

    @staticmethod
    def _resource_for_item(item: ResolvedPlanItem):
        if item.action == PlanAction.CREATE:
            return PlannedRef(item.resource_type, item.plan_id)
        return ExistingRef(item.resource_type, item.database_id)


def verify_generated_configuration(
    generated: GeneratedConfiguration,
) -> VerifiedWorkbookConfiguration:
    """Serialize, resolve against configured databases, and verify workbook intent.

    ``resolve_config`` performs read-only database resolution. This function
    never prepares or applies a persistence plan.
    """

    serialized = serialize_configuration(generated.config)
    plan = resolve_config(serialized.config)
    verifier = _PlanVerifier(generated, plan)
    issues = verifier.verify()
    if issues:
        raise WorkbookPlanVerificationError(issues, plan)
    return VerifiedWorkbookConfiguration(serialized=serialized, plan=plan)
