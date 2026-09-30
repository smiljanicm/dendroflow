# MVP acceptance: fresh VM and PEL trial

The fresh-clone exercise and PEL whole-site RAW ingestion trial completed on
2026-09-30. The operator used Ubuntu 22.04.5 LTS in a new VirtualBox VM,
Python 3.10.12, Docker 29.8.1, and Docker Compose v5.5.1. The captured trial
checkout was `c123b6683a59d2e6a20182b5139e66876e179110`. The subsequently
committed progress-path change is `87787ba`.

The operator ran the [quickstart](quickstart.md) from clone through database
migration, discovery, CONFIG apply, first ingestion, unchanged replay, one
appended row, and a final replay. The first migration succeeded; the second
found no pending migrations. Discovery classified the example source as
unregistered before CONFIG and registered afterward. Ingestion inserted two
initial observations, recognized the unchanged replay, inserted one new
observation after append, and recognized the final replay.

The [PEL trial](pel-trial.md) copied eight configured TOA5 measurement files to
the VM. Discovery reported eight unregistered paths before CONFIG and eight
registered paths afterward. Each file completed a first RAW ingestion; each
unchanged replay returned `already_completed`. The first ingestions reported:

| File | Source rows examined | Observations inserted | Elapsed seconds |
| --- | ---: | ---: | ---: |
| Air Temperature | 103,806 | 415,220 | 294 |
| Battery | 8,496 | 8,496 | 9 |
| Bulk EC | 34,519 | 310,671 | 205 |
| Dendrometers | 103,806 | 519,025 | 504 |
| Permittivity | 34,519 | 310,671 | 202 |
| Relative Humidity | 103,806 | 311,415 | 238 |
| Soil Temp | 34,503 | 310,527 | 242 |
| VWC | 34,520 | 310,680 | 213 |
| **Total** | | **2,496,705** | **1,907** |

Times are wall-clock readings from this VM, not performance guarantees. An
appended complete Battery record produced a new completed ingestion with one
inserted observation and 8,496 unchanged observations. Its following replay
returned `already_completed`.

The evidence log records two earlier Battery append/replay invocations with
exit code `2`, followed by successful invocations. Their initial diagnostics
were overwritten by the reused evidence names, so their cause cannot be
established from the archive. The final JSON reports confirm the append and
replay outcomes. Preserve a distinct output name for each retry in future
operator trials.

After the progress-path change, the operator reported `ruff check src tests`
passing and the full opt-in test gate passing: **1,884 tests passed** with
`DENDROFLOW_INTEGRATION=1`, `DENDROFLOW_FRESH_MIGRATION=1`,
`DENDROFLOW_PACKAGE_SMOKE=1`, and `DENDROFLOW_RECOVERY_DRILL=1`.

## Scope and next stage

This acceptance covers CONFIG, discovery, RAW ingestion of registered and
growing files, migration packaging, and the disposable recovery drills. The
PEL mapping is trial-only: the logger timezone is assumed to be fixed UTC+1,
PEL01–PEL05 and other channel identities are provisional, and Diagnostics and
Modem files were excluded. No scientific quality control, verified production
sensor inventory, lab deployment, built-in scheduling, or notifications were
accepted by this exercise.

Lab deployment should verify logger clock behavior, source paths, and sensor
identities before applying configuration to production. Backup operations and
restore checks follow the [recovery runbook](recovery-runbook.md); scheduling
can initially call the CLI externally.
