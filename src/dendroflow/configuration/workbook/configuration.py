"""Assemble a validated public CONFIG model from workbook comparison results."""

import re
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass

from pydantic import ValidationError

from ..models import ConfigModel
from ..validation import ConfigValidationError, validate_config
from .comparison import (
    ComparisonStatus,
    WorkbookComparison,
    WorkbookReference,
    compare_workbook,
)
from .matching import MatchedWorkbook
from .reader import WorkbookIssue
from .schema import RESOURCE_SHEETS, get_sheet_spec
from .selectors import WorkbookSelectors, build_workbook_selectors

_UPDATE_SECTIONS = {
    "sites": "sites", "location_types": "location_types", "sensor_types": "sensor_types",
    "variables": "variables", "sensor_models": "sensor_models", "sensors": "sensors",
    "locations": "locations", "deployments": "deployments",
}


class WorkbookConfigurationError(ValueError):
    """Unable to create a complete CONFIG model; issues may point to Excel cells."""

    def __init__(self, issues: tuple[WorkbookIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(
            f"{issue.sheet or 'workbook'}"
            f"{'!' + issue.coordinate if issue.coordinate else ''}: {issue.message}"
            for issue in issues
        ))


@dataclass(frozen=True)
class GeneratedConfiguration:
    """Validated CONFIG model and the comparison/selector evidence used to build it."""

    config: ConfigModel
    comparison: WorkbookComparison
    selectors: WorkbookSelectors


class _Generator:
    def __init__(self, matched: MatchedWorkbook, comparison: WorkbookComparison,
                 selectors: WorkbookSelectors):
        self.matched = matched
        self.comparison = comparison
        self.selectors = selectors.selectors
        self.refs: dict[str, dict[str, str]] = {spec.name: {} for spec in RESOURCE_SHEETS}
        self.declarations: dict[str, list[dict]] = {spec.name: [] for spec in RESOURCE_SHEETS}
        self.updates: dict[str, list[dict]] = {name: [] for name in _UPDATE_SECTIONS}
        self.origins: dict[str, tuple[str, dict[str, str]]] = {}
        self.update_origins: dict[str, list[tuple[str, dict[str, str]]]] = {
            name: [] for name in _UPDATE_SECTIONS.values()
        }
        self.issues = []
        for sheet, rows in self.selectors.items():
            for row in rows.values():
                self.refs[sheet][row.alias] = row.alias
        for sheet, rows in matched.rows.items():
            for row in rows:
                self.refs[sheet][row.values["ref"]] = row.values["ref"]

    def ref(self, target: WorkbookReference | str | None, sheet: str, coordinate: str) -> str | None:
        if target is None:
            return None
        if isinstance(target, str):
            alias = target
        elif target.database_id is not None:
            try:
                alias = self.selectors[sheet][target.database_id].alias
            except KeyError as error:
                raise ValueError(f"no verified {sheet} selector for current ID {target.database_id}") from error
        else:
            alias = target.ref
        if alias not in self.refs[sheet]:
            raise ValueError(f"unresolved {sheet} alias {alias!r}")
        return alias

    def record(self, sheet: str, values: dict, origin: WorkbookIssue,
               coordinates: dict[str, str]) -> None:
        index = len(self.declarations[sheet])
        self.declarations[sheet].append(values)
        self.origins[f"{sheet}[{index}]"] = (origin.sheet, coordinates)

    def issue(self, row, sheet: str, field: str, error: Exception) -> None:
        self.issues.append(WorkbookIssue(sheet, row.match.coordinates.get(field), str(error)))

    def declaration(self, sheet: str, row) -> None:
        values = row.match.values
        origin = WorkbookIssue(sheet, row.match.coordinates[get_sheet_spec(sheet).id_column], "CONFIG declaration")
        try:
            ref = values["ref"]
            if sheet in {"sites", "location_types", "sensor_types", "variables"}:
                data = {key: deepcopy(value) for key, value in values.items()
                        if key not in {"site_id", "location_type_id", "sensor_type_id", "variable_id", "ref", "row_role"}}
            elif sheet == "sensor_models":
                data = {"manufacturer": values["manufacturer"], "model": values["model"],
                        "sensor_type": self.ref(values["sensor_type"], "sensor_types", row.match.coordinates["sensor_type"])}
            elif sheet == "sensors":
                data = {"serial_number": values["serial_number"],
                        "sensor_model": self.ref(values["sensor_model"], "sensor_models", row.match.coordinates["sensor_model"]),
                        "description": values["description"]}
            elif sheet == "locations":
                labels = [label for label in self.comparison.rows["location_labels"]
                          if label.match.values["location"] == ref and label.match.values["is_initial"]]
                if len(labels) != 1:
                    raise ValueError("new location requires exactly one initial label row")
                label = labels[0].match.values
                data = {
                    "site": self.ref(values["site"], "sites", row.match.coordinates["site"]),
                    "location_type": self.ref(values["location_type"], "location_types", row.match.coordinates["location_type"]),
                    "initial_label": {"label": label["label"], "valid_from": label["valid_from"], "valid_to": label["valid_to"]},
                    "latitude": values["latitude"], "longitude": values["longitude"],
                    "height_above_ground": values["height_above_ground"], "azimuth": values["azimuth"],
                }
            elif sheet == "location_labels":
                # The initial label for a new location is nested in its declaration.
                if values["is_initial"]:
                    return
                data = {"location": self.ref(values["location"], "locations", row.match.coordinates["location"]),
                        "label": values["label"], "valid_from": values["valid_from"], "valid_to": values["valid_to"]}
            elif sheet == "deployments":
                data = {field: self.ref(values[field], target, row.match.coordinates[field])
                        for field, target in (("sensor", "sensors"), ("location", "locations"), ("variable", "variables"))}
                data.update(valid_from=values["valid_from"], valid_to=values["valid_to"])
            else:
                return
            if ref is not None and sheet != "location_labels":
                data["ref"] = ref
            self.record(sheet, data, origin, row.match.coordinates)
        except (KeyError, TypeError, ValueError) as error:
            self.issue(row, sheet, "ref", error)

    def update(self, sheet: str, row) -> None:
        if row.status != ComparisonStatus.UPDATE:
            return
        spec = get_sheet_spec(sheet)
        selector = self.selectors[sheet][row.match.database_id]
        changes = {}
        try:
            for change in row.changes:
                if change.update_field is None:
                    raise ValueError(f"field {change.field} is not supported for updates")
                value = change.after
                column = next(field for field in spec.fields if field.name == change.field)
                if column.target_sheet is not None and value is not None:
                    value = self.ref(value, column.target_sheet, change.coordinate)
                changes[change.update_field] = deepcopy(value)
            section = _UPDATE_SECTIONS[sheet]
            self.updates[section].append({"update": selector.lookup, "set": changes})
            self.update_origins[section].append((sheet, row.match.coordinates))
        except (KeyError, StopIteration, TypeError, ValueError) as error:
            self.issue(row, sheet, "ref", error)

    def files(self):
        grouped = OrderedDict()
        for row in self.comparison.rows["interfaces"]:
            if row.status != ComparisonStatus.NEW:
                continue
            file_value = row.match.values["file"]
            existing_id = next((key for key, selector in self.selectors["files"].items()
                                if selector.alias == file_value), None)
            if existing_id is not None:
                file_key = ("files", existing_id)
                file_alias = file_value
                current = self.matched.current["files"][existing_id]
                config = current["reader_config"]
                if not isinstance(config, dict) or set(config) != {"reader", "options"}:
                    raise WorkbookConfigurationError((WorkbookIssue(
                        "interfaces", row.match.coordinates["file"], "current file settings cannot be represented",
                    ),))
                file_values = {"path": current["filepath"], "timestamp": {
                    "timezone": current["timestamp_timezone"], "format": current["timestamp_format"],
                }, "reader": {"type": config["reader"], "options": deepcopy(config["options"])}}
                origin = WorkbookIssue("interfaces", row.match.coordinates["file"], "existing file context")
            elif isinstance(file_value, str):
                file_key = ("new", file_value)
                file_alias = file_value
                file_rows = [item for item in self.comparison.rows["files"]
                             if item.match.values["ref"] == file_value and item.status == ComparisonStatus.NEW]
                if len(file_rows) != 1:
                    raise ValueError(f"new file {file_value!r} is missing or ambiguous")
                file_row = file_rows[0]
                values = file_row.match.values
                file_values = {"path": values["path"], "timestamp": {
                    "timezone": values["timestamp_timezone"], "format": values["timestamp_format"],
                }, "reader": {"type": values["reader_type"], "options": deepcopy(values["reader_options"])}}
                origin = WorkbookIssue("files", file_row.match.coordinates["file_id"], "new file context")
            else:
                raise ValueError("interface must refer to an existing or declared file")

            interface = {"deployment": self.ref(row.match.values["deployment"], "deployments",
                                                  row.match.coordinates["deployment"]),
                         "timestamp_column": row.match.values["timestamp_column"],
                         "values_column": row.match.values["values_column"], "unit": row.match.values["unit"]}
            if file_key not in grouped:
                grouped[file_key] = {**file_values, "ref": file_alias, "interfaces": [], "origin": origin}
            grouped[file_key]["interfaces"].append(interface)
        for group in grouped.values():
            origin = group.pop("origin")
            index = len(self.declarations["files"])
            self.declarations["files"].append(group)
            self.origins[f"files[{index}]"] = (origin.sheet, {"file_id": origin.coordinate or ""})

    def generate(self) -> ConfigModel:
        self.comparison.raise_for_errors()
        for spec in RESOURCE_SHEETS:
            for row in self.comparison.rows[spec.name]:
                if row.status == ComparisonStatus.NEW:
                    self.declaration(spec.name, row)
                elif row.status == ComparisonStatus.UPDATE:
                    self.update(spec.name, row)
        try:
            self.files()
        except WorkbookConfigurationError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise WorkbookConfigurationError((WorkbookIssue(None, None, str(error)),)) from error
        if self.issues:
            raise WorkbookConfigurationError(tuple(self.issues))

        references = {sheet: {row.alias: row.lookup for row in rows.values()}
                      for sheet, rows in self.selectors.items() if sheet != "files"}
        payload = {name: self.declarations[name] for name in (
            "sites", "location_types", "sensor_types", "variables", "sensor_models",
            "sensors", "locations", "location_labels", "deployments", "files",
        )}
        payload["references"] = references
        payload["updates"] = self.updates
        try:
            config = ConfigModel.model_validate(payload)
            validate_config(config)
        except (ValidationError, ConfigValidationError) as error:
            issues = []
            if isinstance(error, ConfigValidationError):
                for issue in error.issues:
                    match = re.match(r"([a-z_]+\[\d+\])(?:\.([a-z_]+))?", issue.path)
                    origin = self.origins.get(match.group(1)) if match else None
                    update_match = re.match(r"updates\.([a-z_]+)\[(\d+)\](?:\.set\.([a-z_]+))?", issue.path)
                    if update_match:
                        section, row_index, field = update_match.groups()
                        entries = self.update_origins.get(section, ())
                        if int(row_index) < len(entries):
                            sheet, coordinates = entries[int(row_index)]
                            issues.append(WorkbookIssue(
                                sheet, coordinates.get(field) if field else None,
                                f"{issue.path}: {issue.message}",
                            ))
                            continue
                    if origin is None:
                        issues.append(WorkbookIssue(None, None, f"{issue.path}: {issue.message}"))
                    else:
                        sheet, coordinates = origin
                        field = match.group(2)
                        issues.append(WorkbookIssue(sheet, coordinates.get(field), f"{issue.path}: {issue.message}"))
            else:
                for item in error.errors():
                    location = item.get("loc", ())
                    sheet = location[0] if location and isinstance(location[0], str) else None
                    row_index = location[1] if len(location) > 1 and isinstance(location[1], int) else None
                    field = location[2] if len(location) > 2 and isinstance(location[2], str) else None
                    origin = self.origins.get(f"{sheet}[{row_index}]") if sheet and row_index is not None else None
                    if origin is not None:
                        origin_sheet, coordinates = origin
                        issues.append(WorkbookIssue(
                            origin_sheet,
                            coordinates.get(field) if field else coordinates.get(
                                get_sheet_spec(origin_sheet).id_column,
                            ),
                            f"{'.'.join(map(str, location))}: {item['msg']}",
                        ))
                    else:
                        issues.append(WorkbookIssue(None, None, f"{'.'.join(map(str, location))}: {item['msg']}"))
            raise WorkbookConfigurationError(tuple(issues)) from error
        return config


def generate_configuration(matched: MatchedWorkbook) -> GeneratedConfiguration:
    """Generate references, new declarations and explicit updates as ConfigModel.

    Runs G4.b and G4.c against the same caller-supplied G4.a snapshot, then
    validates the assembled model with the existing CONFIG validator. There is
    no IO, YAML output, baseline persistence or apply. A new declaration may be
    reused by CONFIG resolution; this API does not predict CREATE/REUSE.
    """
    comparison = compare_workbook(matched)
    comparison.raise_for_errors()
    selectors = build_workbook_selectors(matched)
    config = _Generator(matched, comparison, selectors).generate()
    return GeneratedConfiguration(config, comparison, selectors)
