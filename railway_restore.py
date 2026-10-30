#!/usr/bin/env python3
"""
Railway PostgreSQL Backup & Restore Script
==========================================
Usage:
  python railway_restore.py --backup           # Create a new backup
  python railway_restore.py --list             # List available backups
  python railway_restore.py --latest           # Restore latest backup
  python railway_restore.py --file <dump>      # Restore specific file
  python railway_restore.py                    # Interactive restore
"""

import os
import re
import shutil
import sys
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

BACKUP_DIR = Path("backups")

if not DATABASE_URL:
    print("DATABASE_URL environment variable is not set.")
    print("Set it in .env before running this script (it is loaded automatically).")
    sys.exit(1)


def version_tuple(tool_path):
    try:
        out = subprocess.run([tool_path, "--version"], capture_output=True, text=True).stdout
        return tuple(int(x) for x in re.search(r'\d+(\.\d+)+', out).group(0).split('.'))
    except Exception:
        return (0,)


def find_tool(name):
    candidates = []
    which = shutil.which(name)
    if which:
        candidates.append((which, None))
    for tool_path in Path("/usr/lib/postgresql").glob("*/bin/" + name):
        candidates.append((str(tool_path), None))
    for tool_path in Path.home().glob(".opt/*/usr/lib/postgresql/*/bin/" + name):
        lib_matches = sorted(Path(tool_path.parents[4], "lib").glob("*/libpq.so.5*"))
        libdir = str(lib_matches[0].parent) if lib_matches else None
        candidates.append((str(tool_path), libdir))

    if not candidates:
        print(f"{name} not found.")
        print("Install with: brew install postgresql (macOS) or sudo apt install postgresql-client (Ubuntu)")
        return None

    best_path, best_lib = max(candidates, key=lambda c: version_tuple(c[0]))
    best_ver = '.'.join(str(x) for x in version_tuple(best_path))
    print(f"{name} found: {best_ver} ({best_path})")
    return best_path, best_lib


def tool_env(libdir):
    env = os.environ.copy()
    if libdir:
        env['LD_LIBRARY_PATH'] = f"{libdir}:{env['LD_LIBRARY_PATH']}" if env.get('LD_LIBRARY_PATH') else libdir
    return env


def create_backup():
    tool = find_tool("pg_dump")
    if tool is None:
        sys.exit(1)
    dump_bin, env = tool[0], tool_env(tool[1])
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = BACKUP_DIR / f"railway_backup_{timestamp}.dump"

    print(f"\nBacking up database to: {out_path}")
    print("-" * 50)
    result = subprocess.run(
        [
            dump_bin,
            "--dbname", DATABASE_URL,
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file", str(out_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    if result.returncode != 0:
        out_path.unlink(missing_ok=True)
        print(f"Backup FAILED:\n{result.stderr or result.stdout}")
        sys.exit(1)

    if not out_path.exists() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        print(f"Backup produced no data: {out_path.name}")
        sys.exit(1)

    size = out_path.stat().st_size
    size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.1f} MB"
    print(f"Backup complete: {out_path.name} ({size_str})")
    if result.stderr.strip():
        print(f"Warnings:\n{result.stderr.strip()}")


def get_dumps():
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("*.dump"), key=lambda f: f.stat().st_mtime, reverse=True)


def list_backups():
    dumps = get_dumps()
    if not dumps:
        print("No backups found in ./backups/")
        return dumps
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

    with dump_path.open("rb") as fh:
        if fh.read(5) != b"PGDMP":
            print(f"Not a valid PostgreSQL custom-format dump: {dump_path.name}")
            sys.exit(1)

    print(f"\nRestoring from: {dump_path.name}")
    print(f"Database: Railway PostgreSQL")
    print("-" * 50)

    tool = find_tool("pg_restore")
    if tool is None:
        sys.exit(1)
    restore_bin, env = tool[0], tool_env(tool[1])

    confirm = input("This will OVERWRITE all data in the database. Type 'yes' to continue: ").strip().lower()
    if confirm != "yes":
        print("Restore cancelled.")
        return

    print("\nRestoring...")
    result = subprocess.run(
        [
            restore_bin,
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
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    if result.returncode != 0:
        print(f"Restore FAILED:\n{result.stderr or result.stdout}")
        sys.exit(1)

    print("Restore complete!")
    if result.stderr:
        stderr_lines = result.stderr.strip().split("\n")
        print(f"Processed {len([l for l in stderr_lines if 'COPY' in l or 'CREATE' in l])} objects")


def latest_backup():
    dumps = get_dumps()
    if not dumps:
        print("No backups found.")
        sys.exit(1)
    print(f"Latest backup: {dumps[0].name}")
    return dumps[0]


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
    parser = argparse.ArgumentParser(description="Railway PostgreSQL backup & restore tool")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--backup", action="store_true", help="Create a new backup with pg_dump")
    mode.add_argument("--latest", action="store_true", help="Restore latest backup automatically")
    mode.add_argument("--file", metavar="FILE", help="Restore specific dump file")
    mode.add_argument("--list", action="store_true", help="List available backups")

    args = parser.parse_args()

    if args.backup:
        create_backup()
        return

    if args.list:
        list_backups()
    elif args.latest:
        restore_backup(latest_backup())
    elif args.file:
        restore_backup(Path(args.file))
    else:
        interactive_restore()


if __name__ == "__main__":
    main()
