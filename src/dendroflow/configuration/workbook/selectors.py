"""Build public CONFIG lookups verified against the G4.a current snapshot."""

from dataclasses import dataclass

from ..models import (
    DeploymentLookupConfig,
    FileLookupConfig,
    LocationLookupConfig,
    LocationTypeLookupConfig,
    LookupConfig,
    SensorLookupConfig,
    SensorModelLookupConfig,
    SensorTypeLookupConfig,
    SiteLookupConfig,
    VariableLookupConfig,
)
from .comparison import compare_workbook
from .matching import MatchedWorkbook
from .preparation import _text, _timestamp
from .reader import WorkbookIssue
from .schema import get_sheet_spec

_MODELS = {
    "sites": SiteLookupConfig,
    "location_types": LocationTypeLookupConfig,
    "sensor_types": SensorTypeLookupConfig,
    "variables": VariableLookupConfig,
    "sensor_models": SensorModelLookupConfig,
    "sensors": SensorLookupConfig,
    "locations": LocationLookupConfig,
    "deployments": DeploymentLookupConfig,
    "files": FileLookupConfig,
}
_TEXT_FIELDS = {
    "sites": ("site_code",),
    "location_types": ("type",),
    "sensor_types": ("type",),
    "variables": ("variable",),
    "sensor_models": ("manufacturer", "model"),
    "sensors": ("serial_number",),
    "locations": (),
    "deployments": (),
    "files": ("path",),
}
_DEPENDENCIES = {
    "sensors": (("sensor_model", "sensor_models"),),
    "locations": (("site", "sites"),),
    "deployments": (("sensor", "sensors"), ("location", "locations"), ("variable", "variables")),
}


@dataclass(frozen=True)
class WorkbookSelector:
    """One verified current lookup; alias is a workbook ref or a helper ref.

    lookup is a caller-owned public Pydantic lookup model. Dependencies are
    (sheet, database_id) keys in the same set. helper marks omitted dependencies.
    A file lookup is identity evidence, not an executable references.files entry.
    """

    sheet: str
    database_id: int
    alias: str
    lookup: LookupConfig
    dependencies: tuple[tuple[str, int], ...]
    helper: bool


@dataclass(frozen=True)
class WorkbookSelectors:
    """Caller-owned lookup models, indexed by sheet and current database ID.

    IDs are verification evidence only and must not become YAML lookup fields.
    Labels/interfaces have no public lookup models and are not in this mapping.
    """

    selectors: dict[str, dict[int, WorkbookSelector]]


class WorkbookSelectorError(ValueError):
    """A required lookup cannot unambiguously select its intended current ID."""

    def __init__(self, issues: tuple[WorkbookIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(
            f"{issue.sheet or 'workbook'}"
            f"{'!' + issue.coordinate if issue.coordinate else ''}: {issue.message}"
            for issue in issues
        ))


class _Builder:
    def __init__(self, matched: MatchedWorkbook):
        self.current = matched.current
        self.built: dict[tuple[str, int], WorkbookSelector] = {}
        self.aliases = {
            (sheet, row.database_id): row.values["ref"]
            for sheet, rows in matched.rows.items() if sheet in _MODELS
            for row in rows if row.database_id is not None
        }
        # Reserve new declaration aliases too, within each CONFIG namespace.
        self.used = {
            sheet: {row.values["ref"] for row in matched.rows[sheet]}
            for sheet in _MODELS
        }
        self.histories = {}
        for row in self.current["location_labels"].values():
            self.histories.setdefault(row["location_id"], []).append(row)
        self.initials = {}

    def initial_label(self, key: int):
        if key not in self.initials:
            history = self.histories.get(key, ())
            first = min(history, key=lambda row: (
                _timestamp(row["valid_from"]), row["location_label_id"],
            )) if history else None
            self.initials[key] = None if first is None else first["label"]
        return self.initials[key]

    def alias(self, sheet: str, key: int) -> str:
        if (sheet, key) in self.aliases:
            return self.aliases[sheet, key]
        base = f"current_{get_sheet_spec(sheet).resource_type}_{key}"
        alias, suffix = base, 2
        while alias in self.used[sheet]:
            alias = f"{base}_{suffix}"
            suffix += 1
        self.used[sheet].add(alias)
        return alias

    def build(self, sheet: str, key: int) -> WorkbookSelector:
        if (sheet, key) in self.built:
            return self.built[sheet, key]
        try:
            row = self.current[sheet][key]
        except KeyError as error:
            raise ValueError(f"required current {sheet} ID {key} is missing") from error
        values, criteria, dependencies = {}, {}, []
        for field in _TEXT_FIELDS[sheet]:
            stored = "filepath" if field == "path" else field
            values[field] = _text(row[stored])
            criteria[stored] = values[field]
        for field, target in _DEPENDENCIES.get(sheet, ()):
            target_id = row[f"{field}_id"]
            try:
                dependency = self.build(target, target_id)
            except ValueError as error:
                raise ValueError(f"{sheet} ID {key} needs {target} ID {target_id}: {error}") from error
            values[field] = dependency.alias
            criteria[f"{field}_id"] = target_id
            dependencies.append((target, target_id))
        if sheet == "locations":
            label = self.initial_label(key)
            if label is None:
                raise ValueError(f"location ID {key} has no initial label for its public lookup")
            values["initial_label"] = _text(label)
        if sheet == "deployments":
            values["valid_from"] = _timestamp(row["valid_from"])

        lookup = _MODELS[sheet].model_validate(values)
        if lookup.model_dump(exclude_none=True) != values:
            raise ValueError(f"{sheet} ID {key} lookup would normalize current identity values")

        # Match all identifying fields, just as CONFIG's conjunctive lookups do.
        # Search the entire snapshot, not only rows present in the workbook.
        candidates = []
        for candidate_id, candidate in sorted(self.current[sheet].items()):
            if any(candidate[field] != value for field, value in criteria.items()):
                continue
            if sheet == "locations" and self.initial_label(candidate_id) != values["initial_label"]:
                continue  # SQL's lateral inner join also excludes unlabeled locations.
            if sheet == "deployments" and _timestamp(candidate["valid_from"]) != values["valid_from"]:
                continue
            candidates.append(candidate_id)
        if candidates != [key]:
            raise ValueError(
                f"{sheet} ID {key} lookup must identify only that ID; matched IDs {candidates}",
            )
        result = WorkbookSelector(
            sheet, key, self.alias(sheet, key), lookup, tuple(dependencies),
            (sheet, key) not in self.aliases,
        )
        self.built[sheet, key] = result
        return result


def build_workbook_selectors(matched: MatchedWorkbook) -> WorkbookSelectors:
    """Build existing selectors from current values, after G4.b passes.

    Accept an unmodified G4.a result. Recompute G4.b on that same snapshot to
    reject blocked edits. No database or file IO, mutation, CONFIG declarations,
    updates, or YAML output. Uniqueness is verified in the supplied full source
    snapshot; live resolution must be verified again during G4.e/G4.f.

    All included existing rows with a public lookup receive a selector. Current
    lookup dependencies may add helper references, including omitted records;
    helpers grant no edit role. Labels and interfaces remain comparison context,
    and new rows stay unresolved. Files get FileLookupConfig identity evidence,
    but existing CONFIG does not resolve references.files: G4.d must nest new
    interfaces in a compatible file declaration using the current file settings.
    """
    compare_workbook(matched).raise_for_errors()
    builder = _Builder(matched)
    issues = []
    for sheet in _MODELS:
        rows = sorted(
            (row for row in matched.rows[sheet] if row.database_id is not None),
            key=lambda row: row.database_id,
        )
        for row in rows:
            try:
                builder.build(sheet, row.database_id)
            except (TypeError, ValueError, OverflowError, RecursionError) as error:
                issues.append(WorkbookIssue(
                    sheet, row.coordinates[get_sheet_spec(sheet).id_column], str(error),
                ))
    if issues:
        raise WorkbookSelectorError(tuple(issues))
    return WorkbookSelectors({
        sheet: {
            key: builder.built[sheet, key]
            for name, key in sorted(builder.built) if name == sheet
        } for sheet in _MODELS
    })
