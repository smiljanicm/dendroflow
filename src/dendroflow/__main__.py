import sys

from dendroflow.database import DATABASES
from dendroflow.migrations import migrate_database


def migrate() -> None:
    """Apply pending migrations to all DendroFlow databases."""
    for database in DATABASES:
        print(f"Migrating {database}...")

        try:
            applied_versions = migrate_database(database)
        except Exception as error:
            print(f"  Migration failed: {error}", file=sys.stderr)
            raise SystemExit(1)

        if applied_versions:
            for version in applied_versions:
                print(f"  Applied {version}")
        else:
            print("  No pending migrations")

    print("Migration complete.")


def main() -> None:
    """Run the DendroFlow command-line interface."""
    if len(sys.argv) < 2:
        print("Usage: python -m dendroflow <command>")
        return

    command = sys.argv[1]

    if command == "migrate":
        migrate()
        return

    print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
