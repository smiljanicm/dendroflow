"""Opt-in acceptance test for the installed DendroFlow wheel."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("DENDROFLOW_PACKAGE_SMOKE") != "1",
    reason="Set DENDROFLOW_PACKAGE_SMOKE=1 to build and install a wheel",
)

ROOT = Path(__file__).resolve().parents[1]
DATABASES = ("metadata", "raw", "clean")


def _run(*args, cwd, env):
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"{' '.join(str(arg) for arg in args)} failed:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    return result.stdout


def test_installed_wheel_finds_exact_migrations_outside_checkout(tmp_path):
    """Install in a fresh venv and read the bundled SQL from another directory."""
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    venv = tmp_path / "venv"

    # Clear the two common ways a subprocess might still import checkout code.
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("DENDROFLOW_ROOT", None)

    _run(
        sys.executable, "-m", "pip", "wheel", "--no-deps",
        "--wheel-dir", str(wheelhouse), str(ROOT), cwd=unrelated, env=env,
    )
    wheels = list(wheelhouse.glob("dendroflow-*.whl"))
    assert len(wheels) == 1

    _run(sys.executable, "-m", "venv", str(venv), cwd=unrelated, env=env)
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    cli = scripts / ("dendroflow.exe" if os.name == "nt" else "dendroflow")
    _run(
        python, "-m", "pip", "install", "--no-input", str(wheels[0]),
        cwd=unrelated, env=env,
    )

    help_output = _run(cli, "--help", cwd=unrelated, env=env)
    assert "migrate" in help_output
    assert "ingest" in help_output
    assert "discover" in help_output
    assert "config" in help_output

    inspection = _run(
        python, "-c",
        """
import hashlib
import json
from pathlib import Path
from dendroflow import migrations

result = {
    "module": str(Path(migrations.__file__).resolve()),
    "files": {
        database: [
            {
                "path": str(path.resolve()),
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in migrations.get_migration_files("dendroflow_" + database)
        ]
        for database in ("metadata", "raw", "clean")
    },
}
print(json.dumps(result))
""",
        cwd=unrelated,
        env=env,
    )
    installed = json.loads(inspection)
    assert Path(installed["module"]).is_relative_to(venv)

    for database in DATABASES:
        source = sorted((ROOT / "db" / database / "migrations").glob("*.sql"))
        expected = [
            {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in source
        ]
        assert expected
        actual = installed["files"][database]
        assert [{"name": row["name"], "sha256": row["sha256"]} for row in actual] == (
            expected
        )
        assert all(Path(row["path"]).is_relative_to(venv) for row in actual)
