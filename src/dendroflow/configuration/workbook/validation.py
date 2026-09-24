"""Check parsed workbook identities, references and scope without database IO."""

from collections import defaultdict

from .parsing import ParsedWorkbook
from .reader import WorkbookIssue
from .schema import INFO_SHEET, RESOURCE_SHEETS

_SPECS = {spec.name: spec for spec in RESOURCE_SHEETS}
_OWNERS = {
    "locations": "site",
    "location_labels": "location",
    "deployments": "location",
    "interfaces": "deployment",
}


class WorkbookValidationError(ValueError):
    """Workbook consistency issues; no database comparison has been performed."""

    def __init__(self, issues: tuple[WorkbookIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(
            f"{issue.sheet or 'workbook'}"
            f"{'!' + issue.coordinate if issue.coordinate else ''}: {issue.message}"
            for issue in issues
        ))


def _check_structure(parsed: ParsedWorkbook) -> None:
    if set(parsed.frames) != set(_SPECS) or set(parsed.coordinates) != set(_SPECS):
        raise WorkbookValidationError((WorkbookIssue(None, None, "expected eleven frames and coordinate frames"),))
    for name, spec in _SPECS.items():
        frame, coordinates = parsed.frames[name], parsed.coordinates[name]
        if (
            not frame.columns.is_unique or set(frame.columns) != set(spec.headers)
            or not coordinates.columns.is_unique or set(coordinates.columns) != set(spec.headers)
            or not frame.index.is_unique or not frame.index.equals(coordinates.index)
        ):
            raise WorkbookValidationError((WorkbookIssue(name, None, "unaligned values and coordinates"),))


class _Checks:
    def __init__(self, parsed: ParsedWorkbook):
        self.parsed = parsed
        self.rows = {name: frame.to_dict("records") for name, frame in parsed.frames.items()}
        self.refs = {name: defaultdict(list) for name in _SPECS}
        self.edges = {}
        self.issues = []

    def issue(self, name, index, field, message):
        coordinate = self.parsed.coordinates[name].iloc[index][field]
        self.issues.append(WorkbookIssue(name, coordinate, f"{field}: {message}"))

    def identities(self):
        for name, spec in _SPECS.items():
            ids = defaultdict(list)
            for index, row in enumerate(self.rows[name]):
                self.refs[name][row["ref"]].append(index)
                if row[spec.id_column] is not None:
                    ids[row[spec.id_column]].append(index)
            for field, groups in ((spec.id_column, ids), ("ref", self.refs[name])):
                for indexes in groups.values():
                    if len(indexes) > 1:
                        for index in indexes:
                            self.issue(name, index, field, "duplicate value within this sheet")

    def references(self):
        for name, spec in _SPECS.items():
            for index, row in enumerate(self.rows[name]):
                for column in spec.fields:
                    if column.target_sheet is None or row[column.name] is None:
                        continue
                    matches = self.refs[column.target_sheet].get(row[column.name], ())
                    if len(matches) != 1:
                        problem = "unresolved" if not matches else "ambiguous"
                        self.issue(name, index, column.name, f"{problem} reference to {column.target_sheet}.ref")
                    else:
                        self.edges[(name, index, column.name)] = (column.target_sheet, matches[0])

    def site_cycles(self):
        complete = set()
        for start in range(len(self.rows["sites"])):
            current = ("sites", start)
            path = []
            positions = {}
            while current is not None and current not in complete:
                if current in positions:
                    for name, index in path[positions[current]:]:
                        self.issue(name, index, "parent", "site ancestry contains a cycle")
                    break
                positions[current] = len(path)
                path.append(current)
                current = self.edges.get((*current, "parent"))
            complete.update(path)

    def roles(self):
        scope = self.parsed.metadata.scope
        selected = set(self.parsed.metadata.site_ids)
        for name, spec in _SPECS.items():
            for index, row in enumerate(self.rows[name]):
                is_new = row[spec.id_column] is None
                expected = "edit"
                if scope == "template" and not is_new:
                    self.issue(name, index, spec.id_column, "template rows must have blank database IDs")
                if scope == "sites":
                    if name == "sites":
                        if is_new:
                            self.issue(name, index, spec.id_column, "new sites require all or template scope")
                        elif row[spec.id_column] not in selected:
                            expected = "reference"
                    elif not is_new and name not in _OWNERS:
                        expected = "reference"
                if row["row_role"] != expected:
                    self.issue(name, index, "row_role", f"expected {expected} for this row and scope")

    def site_scope(self):
        selected = set(self.parsed.metadata.site_ids)
        selected_sites = {
            ("sites", index) for index, row in enumerate(self.rows["sites"])
            if row["site_id"] in selected
        }
        represented = {self.rows[name][index]["site_id"] for name, index in selected_sites}
        for key in sorted(selected - represented):
            self.issues.append(WorkbookIssue(INFO_SHEET, None, f"site_ids: selected site {key} is missing from sites"))

        roots = set(selected_sites)
        for name, field in _OWNERS.items():
            for index in range(len(self.rows[name])):
                current = (name, index)
                while current is not None and current[0] in _OWNERS:
                    owner_field = _OWNERS[current[0]]
                    current = self.edges.get((*current, owner_field))
                if current in selected_sites:
                    roots.add((name, index))
                elif current is not None:
                    self.issue(name, index, field, "relationship is outside the selected sites")

        # Follow every dependency of selected-site records, including ancestor
        # sites and shared catalogue rows. A shared file never pulls in other
        # interfaces because references point from interface to file.
        included = set(roots)
        pending = list(roots)
        while pending:
            name, index = pending.pop()
            for column in _SPECS[name].fields:
                target = self.edges.get((name, index, column.name))
                if target is not None and target not in included:
                    included.add(target)
                    pending.append(target)
        for name in _SPECS:
            if name in _OWNERS:
                continue  # Already checked via its ownership chain.
            for index in range(len(self.rows[name])):
                if (name, index) not in included:
                    self.issue(name, index, "ref", "row is not a selected site or a required dependency")

    def initial_labels(self):
        labels = defaultdict(list)
        for index, row in enumerate(self.rows["location_labels"]):
            target = self.edges.get(("location_labels", index, "location"))
            if target is not None:
                labels[target[1]].append((index, row))
        for index, location in enumerate(self.rows["locations"]):
            if len(self.refs["locations"][location["ref"]]) != 1:
                continue  # References to this location are already ambiguous.
            associated = labels[index]
            initial = [(i, row) for i, row in associated if row["is_initial"]]
            if location["location_id"] is None:
                for label_index, row in associated:
                    if row["location_label_id"] is not None:
                        self.issue("location_labels", label_index, "location", "existing labels cannot belong to a new location")
                new_initial = [row for _, row in initial if row["location_label_id"] is None]
                if len(new_initial) != 1:
                    self.issue("locations", index, "ref", "new location requires exactly one new initial label")
            else:
                for label_index, row in initial:
                    if row["location_label_id"] is None:
                        self.issue("location_labels", label_index, "is_initial", "a new label for an existing location must not be initial")
            if len(initial) > 1:
                for label_index, _ in initial:
                    self.issue("location_labels", label_index, "is_initial", "multiple initial labels for one location")

    def new_files(self):
        supported = {
            self.edges[("interfaces", index, "file")][1]
            for index, row in enumerate(self.rows["interfaces"])
            if row["interface_id"] is None and ("interfaces", index, "file") in self.edges
        }
        for index, row in enumerate(self.rows["files"]):
            if row["file_id"] is None and index not in supported:
                self.issue("files", index, "ref", "new file requires at least one new interface")


def validate_workbook(parsed: ParsedWorkbook) -> None:
    """Raise located errors for inconsistent parsed workbook contents.

    Pass an unmodified parse_workbook result. Successful validation returns None
    without changing frames. These are offline checks, not verification of IDs,
    ownership, immutable fields or row roles against the live database. Missing
    rows do not request deletion. Full CONFIG validation and reviewed planning
    remain required before apply.
    """
    if not isinstance(parsed, ParsedWorkbook):
        raise TypeError("parsed must be a ParsedWorkbook from parse_workbook")
    _check_structure(parsed)
    checks = _Checks(parsed)
    checks.identities()
    checks.references()
    checks.site_cycles()
    checks.roles()
    if parsed.metadata.scope == "sites":
        checks.site_scope()
    checks.initial_labels()
    checks.new_files()
    if checks.issues:
        raise WorkbookValidationError(tuple(checks.issues))
