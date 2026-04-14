#!/usr/bin/env python3
"""
Railway PostgreSQL Restore Script
==================================
Usage:
  python railway_restore.py                    # Interactive restore
  python railway_restore.py --latest           # Restore latest backup
  python railway_restore.py --file <dump>      # Restore specific file
  python railway_restore.py --list             # List available backups
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime
from pathlib import Path


DATABASE_URL = "postgresql://postgres:NRxQKkDqxjjyUaIShsCTEgmMRqDuJEMY@turntable.proxy.rlwy.net:27386/railway"
BACKUP_DIR = Path("backups")


def check_pg_restore():
    try:
        result = subprocess.run(["pg_restore", "--version"], capture_output=True, text=True)
        print(f"pg_restore found: {result.stdout.strip()}")
        return True
    except FileNotFoundError:
        print("pg_restore not found.")
        print("Install with: brew install postgresql (macOS) or sudo apt install postgresql-client (Ubuntu)")
        return False


def list_backups():
    dumps = sorted(BACKUP_DIR.glob("*.dump"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not dumps:
        print("No backups found in ./backups/")
        return []
    print(f"\nAvailable backups in {BACKUP_DIR.resolve()}:\n")
    print(f"  {'#':<4} {'Filename':<45} {'Size':>10} {'Modified'}")
    print("  " + "-" * 75)
    for i, f in enumerate(dumps, 1):
        size = f.stat().st_size
        size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.1f} MB"
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {i:<4} {f.name:<45} {size_str:>10} {mtime}")
    print()
    return dumps


def restore_backup(dump_path: Path):
    if not dump_path.exists():
        print(f"File not found: {dump_path}")
        sys.exit(1)

    if dump_path.stat().st_size == 0:
        print(f"File is empty (0 bytes): {dump_path.name}")
        sys.exit(1)

    print(f"\nRestoring from: {dump_path.name}")
    print(f"Database: Railway PostgreSQL")
    print("-" * 50)

    confirm = input("This will OVERWRITE all data in the database. Type 'yes' to continue: ").strip().lower()
    if confirm != "yes":
        print("Restore cancelled.")
        return

    print("\nRestoring...")
    result = subprocess.run(
        [
            "pg_restore",
            "--dbname", DATABASE_URL,
            "--no-owner",
            "--no-acl",
            "--clean",
            "--if-exists",
            "-v",
            str(dump_path),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 and "ERROR" in result.stderr:
        print(f"Restore FAILED:\n{result.stderr}")
        sys.exit(1)

    print("Restore complete!")
    if result.stderr:
        stderr_lines = result.stderr.strip().split("\n")
        print(f"Processed {len([l for l in stderr_lines if 'COPY' in l or 'CREATE' in l])} objects")


def interactive_restore():
    dumps = list_backups()
    if not dumps:
        return

    try:
        choice = input("Enter backup number to restore (or 'q' to quit): ").strip()
        if choice.lower() == 'q':
            return
        idx = int(choice) - 1
        if 0 <= idx < len(dumps):
            restore_backup(dumps[idx])
        else:
            print("Invalid selection.")
    except ValueError:
        print("Please enter a valid number.")


def main():
    parser = argparse.ArgumentParser(description="Railway PostgreSQL restore tool")
    parser.add_argument("--latest", action="store_true", help="Restore latest backup automatically")
    parser.add_argument("--file", metavar="FILE", help="Restore specific dump file")
    parser.add_argument("--list", action="store_true", help="List available backups")

    args = parser.parse_args()

    if not check_pg_restore():
        sys.exit(1)

    if args.list:
        list_backups()
    elif args.latest:
        dumps = sorted(BACKUP_DIR.glob("*.dump"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not dumps:
            print("No backups found.")
            sys.exit(1)
        print(f"Latest backup: {dumps[0].name}")
        restore_backup(dumps[0])
    elif args.file:
        restore_backup(Path(args.file))
    else:
        interactive_restore()


if __name__ == "__main__":
    main()
