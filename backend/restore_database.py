import argparse
import sqlite3
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parent / "parking.db"


def restore_database(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Backup not found: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore Parking AI SQLite database")
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    restore_database(args.source, args.destination)
    print(f"Database restored to: {args.destination}")


if __name__ == "__main__":
    main()
