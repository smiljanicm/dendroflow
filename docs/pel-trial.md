# MVP4b: PEL whole-site ingestion trial

This is a **VM-only acceptance exercise** using a copy of the supplied
`PEL_.zip` archive. The configuration in
[`examples/pel-trial/config.yaml`](../examples/pel-trial/config.yaml) registers
eight measurement TOA5 files from one site. `PEL_Diagnostics.dat` and
`PEL_Modem.dat` are entirely out of scope. It is not a production sensor inventory or
quality-controlled dataset. Keep the original source files untouched.

## Mapping and limits

The logger is assumed to record fixed German winter time (UTC+1) throughout
the year. The IANA zone `Etc/GMT-1` has that fixed offset; the sign looks
reversed because of the `Etc/GMT` naming convention. Do not change it to
`Europe/Berlin`: the files contain 02:xx timestamps on both daylight-saving
change dates, and this trial assumes no clock changes. Correct this assumption
before applying if the logger clock was configured differently.

The selected files use the second physical line as their CSV header. The first, third,
and fourth lines are skipped (`skiprows: [0, 2, 3]`); `NAN` is treated as a
missing numeric value. Data begins at physical line five. The timestamp format
is `%Y-%m-%d %H:%M:%S`. Each file is read in 250-row chunks.

| Source | Numeric interfaces | Excluded from RAW |
| --- | ---: | --- |
| `PEL_Air_Temperature.dat` | 4 | `RECORD` |
| `PEL_Battery.dat` | 1 | `RECORD`, `BattV_TMn` (time of minimum) |
| `PEL_Bulk_EC.dat` | 9 | `RECORD` |
| `PEL_Dendrometers.dat` | 5 | `RECORD` |
| `PEL_Permittivity.dat` | 9 | `RECORD` |
| `PEL_Relative_Humidity.dat` | 3 | `RECORD` |
| `PEL_Soil_Temp.dat` | 9 | `RECORD` |
| `PEL_VWC.dat` | 9 | `RECORD` |

There are 49 numeric source interfaces and roughly 2.50 million potential
observations across the eight selected files. The copies contain identical repeated
timestamp records in some files; ingestion should deduplicate or recognize
those matches. Missing values and implausible measurements remain RAW values;
this exercise does not perform quality control.

The 18 location and sensor identities are **provisional channel identities**:
PEL01–PEL05 for dendrometer channels (1)–(5), air channels at 2, 5, and 10 m,
soil channels at nine depths, and one logger channel. They do not claim known
tree assignments, manufacturer, or serial numbers. Trial variables distinguish
five-minute and hourly battery minima to prevent overlapping observations
from being treated as the same RAW identity. A production configuration must
use a verified sensor and location inventory.

Existing initial location-label text cannot be edited by the current CONFIG
workbook. A later label trial can add a **new dated label** to a location's
history; it does not rewrite PEL01–PEL05. Keep this trial database separate
from a future production database.

## 1. Copy the archive into the VM

Complete the fresh-clone quickstart first. From the repository root inside
the VM, with the virtual environment activated, copy `PEL_.zip` to the VM's
`~/Downloads` directory. Do not commit or modify the source archive.

```bash
mkdir -p .demo/PEL
python - <<'PY'
from pathlib import Path
from zipfile import ZipFile
import yaml

config = yaml.safe_load(Path('examples/pel-trial/config.yaml').read_text())
names = {Path(file['path']).name for file in config['files']}
with ZipFile(Path.home() / 'Downloads/PEL_.zip') as archive:
    for name in sorted(names):
        (Path('.demo/PEL') / name).write_bytes(archive.read(name))
print(f'Copied {len(names)} configured files')
PY
find .demo/PEL -maxdepth 1 -type f -name 'PEL_*.dat' | wc -l
```

Start with an empty `.demo/PEL` directory. The count must be **8**; the two
excluded files are left in the archive. The configuration paths are relative to the
repository root, so run every later command from that directory. The `.demo`
directory is ignored by Git. Ensure that the VM has space for the extracted
files, database, and several full-size ingestion snapshots.

Discover the copies before registration:

```bash
dendroflow discover --root .demo/PEL --include '*.dat' --json
```

An exit code of `1` and eight `unregistered` entries are expected.

## 2. Review and apply the site configuration

```bash
dendroflow config validate examples/pel-trial/config.yaml
dendroflow config plan examples/pel-trial/config.yaml > .demo/pel-plan.txt
less .demo/pel-plan.txt
dendroflow config apply examples/pel-trial/config.yaml --yes
dendroflow discover --root .demo/PEL --include '*.dat' --json \
  > .demo/pel-registered.json
```

Apply only after reviewing the plan for one site, eight files, 49 deployments,
and 49 interfaces. Planning and application require the quickstart PostgreSQL
database. The final discovery should exit `0` and show eight `registered` files.
List their actual IDs rather than assuming the IDs assigned by another VM:

```bash
python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path('.demo/pel-registered.json').read_text())
for file in report['files']:
    print(file['file_id'], Path(file['path']).name, file['interface_count'])
PY
```

## 3. Ingest the Battery copy, replay, then append

Use the `file_id` printed for `PEL_Battery.dat` in place of `BATTERY_ID`:

```bash
dendroflow ingest --file-id BATTERY_ID --json | tee .demo/pel-battery-first.json
dendroflow ingest --file-id BATTERY_ID --json | tee .demo/pel-battery-replay.json
```

The first result should be `completed`, with 8,496 source rows and 8,496
inserted observations. The second should be `already_completed` with no new
observations. The archive's Battery file ended at local time
`2026-09-29 15:00:00`, record 19417. Append **one synthetic, complete row to
the VM copy only**:

```bash
printf '"2026-09-29 16:00:00",19418,12.57,"2026-09-29 15:20:00"\n' \
  >> .demo/PEL/PEL_Battery.dat
dendroflow ingest --file-id BATTERY_ID --json | tee .demo/pel-battery-append.json
dendroflow ingest --file-id BATTERY_ID --json | tee .demo/pel-battery-final-replay.json
```

The append run should report a new snapshot/version and one inserted
observation. It may count the preceding rows as unchanged. The final replay
should be `already_completed`. Run the append block only once; inspect the
file tail before repeating it after a partial trial.

## 4. Ingest the remaining registered files in stages

Use the IDs from discovery, one command per file. Begin with an environmental
table such as `PEL_Bulk_EC.dat`; then proceed through the remaining tables.
Record each JSON report in `.demo/`. Avoid `--all` for this trial: the
quickstart example is also registered in the same database, and a failed
large file should not obscure the smaller-file result.

```bash
dendroflow ingest --file-id FILE_ID --json | tee .demo/pel-one-file.json
```

The selected files are large enough for this to take substantial time on a
small VM. Monitor VM free disk space and batch progress. If an ingestion
returns `deferred` or `failed`, keep its JSON report and do not overwrite or
truncate the copied source. A later invocation can resume supported
interrupted runs from their snapshots. A repeat of each completed file should
return `already_completed`.

The scientific plausibility of measurements is outside this RAW acceptance
test. Some 10 m air-temperature and relative-humidity values are negative;
preserve the source values and investigate them separately during future
quality control.
