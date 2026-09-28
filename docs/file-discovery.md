# File discovery

## Purpose and limits

File discovery identifies files under operator-selected directories and compares
their paths with source-file registrations in the RAW database. It helps an
operator find files that need configuration before ingestion.

Discovery is read-only. It does not register files, infer sensor interfaces,
read file contents, calculate file hashes, or store scan history. A file that
still needs configuration appears in each later scan until the operator
registers it or changes the scan scope.

Discovery is a separate operation from ingestion. Ingestion continues to
process registered files, including registered files that grow over time.
Operators may run discovery manually or schedule it externally. The initial
workflow does not include a scheduler or notifications.

## Command contract

The command accepts one or more scan roots. Recursive traversal is opt-in.

```bash
dendroflow discover --root /data/logger
dendroflow discover --root /data/logger --recursive --include '*.csv'
dendroflow discover --root /data/logger --root /data/archive \
  --recursive --include '*.csv' --exclude 'temporary/**' --json
```

Options:

- `--root PATH`: directory to scan; may be repeated. At least one root is
  required. A root must exist and be a directory.
- `--recursive`: include subdirectories. Without it, scan only files directly
  inside each root.
- `--include GLOB`: include paths matching a shell-style glob relative to a
  scan root. May be repeated; a path is included when it matches any include
  pattern. If omitted, all regular files in scope are included.
- `--exclude GLOB`: exclude paths matching a shell-style glob relative to a
  scan root. May be repeated. Exclusions take precedence over inclusions.
- `--json`: emit one machine-readable JSON report to standard output.

The command reads registrations from the currently selected DendroFlow
database target, which defaults to `local`, using the same target settings as
the other CLI commands.

Patterns use paths relative to a root with forward slashes, including on
Windows. For example, `*.csv` matches CSV files at the root, while
`**/*.csv` matches CSV files at any depth. Matching is case-sensitive.
Overlapping roots do not duplicate a discovered path in the report.

The scan considers regular files only. It does not follow symbolic links to
files or directories. This avoids traversing outside a selected root or
reporting the same physical file through multiple paths. A later stage may
add an explicit link-following option if the deployment needs it.

## Path matching and scope

A discovered file is compared with registered `files.filepath` values from
the selected database target. Paths are normalized to absolute paths using
the process working directory for relative registered paths, matching how
ingestion resolves a relative source path. Absolute paths are recommended for
registered files that will be processed by scheduled commands, because their
meaning should not depend on the working directory.

Matching uses the normalized path only. Discovery does not identify duplicate
content at different paths. It reports each unique normalized discovered path
once, even if roots overlap.

Only registrations whose normalized paths fall under one of the selected
roots and match the include/exclude filters are in scope for missing-file
checks. With recursive scanning disabled, only paths directly inside a root
are in scope; nested registrations are not considered missing. A registration
outside the selected roots is not considered missing. An excluded registered
path is outside the scan scope.

## Reported file states

Each included discovered file has one state:

- `unregistered`: no registered file has the same normalized path. The
  operator can review it and add it through the CONFIG workbook workflow.
- `needs_configuration`: the path is registered, but has no source
  interfaces. Complete its interfaces before ingestion.
- `registered`: the path is registered and has one or more source interfaces.

A registered path in scope that does not exist on disk is reported as
`missing`. Discovery does not delete or modify that registration.

The report includes normalized path, state, and file ID when one exists. For
registered files it also includes the number of configured interfaces.
If distinct registrations normalize to the same path, comparison reports an
explicit error instead of choosing one registration.

## Incomplete scans

The command reports missing registrations only for roots whose scan completed.
If a root or subdirectory cannot be read, the report identifies the path and
error and marks that root incomplete. Discovered files from readable
directories are still reported, but registrations that might be under an
unreadable part of that root are not classified as missing.

An incomplete scan never claims the whole selected scope was checked. The
operator should resolve the access problem and rerun discovery before acting
on missing-file results.

## Output and exit codes

Text output summarizes each root, file state, and scan error. With `--json`,
the command emits exactly one JSON object with `schema_version: 1`,
`target_environment`, `complete`, a summary, a `files` array, and a
`scan_errors` array. File entries include `path`, `state`, nullable
`file_id`, and nullable `interface_count`. Each scan error includes the
affected path and an operator-readable message. JSON output does not include
tracebacks or database credentials.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Every root was scanned and no files need configuration; no registered files in scope are missing. |
| `1` | The scan completed and found an unregistered file, a registered file needing interfaces, or a missing registered file. |
| `2` | Invalid arguments, invalid database target, or database error prevented a meaningful comparison. |
| `3` | At least one root could not be scanned completely and no actionable file state was found. |

If a partial scan also finds actionable file states, the command returns `1`;
the report's `complete` field remains false and lists scan errors. This gives
the operator both the findings and the need to resolve incomplete coverage.

## Acceptance criteria

- Repeated scans of the same tree produce the same file states unless the
  filesystem or registrations change.
- Scanning does not write to the METADATA or RAW databases or alter source
  files.
- Registered growing files remain `registered`; their changed contents are
  handled by the ingestion workflow.
- A new path is `unregistered` until configured through the existing CONFIG
  workflow.
- Missing-file results are limited to fully scanned roots and paths within the
  selected filters.
- JSON has one stable, versioned document suitable for a later external
  scheduler.
