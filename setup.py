"""Include the repository's canonical SQL migrations in built packages."""

from pathlib import Path
from shutil import copy2

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithMigrations(build_py):
    def _migration_outputs(self) -> list[Path]:
        root = Path(__file__).resolve().parent
        migrations = sorted((root / "db").glob("*/migrations/*.sql"))
        if not migrations:
            raise RuntimeError("No SQL migrations found under db/")
        return [
            Path(self.build_lib) / "dendroflow" / "sql" / path.relative_to(root / "db")
            for path in migrations
        ]

    def run(self) -> None:
        super().run()
        root = Path(__file__).resolve().parent
        for source in sorted((root / "db").glob("*/migrations/*.sql")):
            destination = (
                Path(self.build_lib)
                / "dendroflow"
                / "sql"
                / source.relative_to(root / "db")
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy2(source, destination)

    def get_outputs(self, include_bytecode: int = 1) -> list[str]:
        return super().get_outputs(include_bytecode) + [
            str(path) for path in self._migration_outputs()
        ]


setup(cmdclass={"build_py": BuildWithMigrations})
