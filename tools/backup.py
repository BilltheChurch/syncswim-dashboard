"""Sync data/ to a remote backup target.

Wraps ``rclone`` (cloud) or ``rsync`` (local/SSH). Designed to run
from cron unattended:

    */15 * * * * /usr/bin/python3 /path/to/tools/backup.py

Target resolution priority (highest first):
    1. ``--target`` CLI arg
    2. ``BACKUP_TARGET`` env var
    3. ``data/.backup_target`` (single-line file with the target string)

Backend choice:
    - target starts with ``/`` or contains ``@`` before ``:`` → rsync
    - otherwise prefer rclone (assumes remote already configured),
      fall back to rsync if rclone isn't installed

Failure mode: every error path **exits 0** and logs to
``data/.backup.log``. Cron MUST NOT email the user every 15 minutes
because of a flaky wifi or temporarily-missing rclone — backup is
best-effort, not a hard dependency.

Common targets:
    rclone:  "icloud:syncswim/"            (after ``rclone config``)
             "s3:my-bucket/syncswim/"
             "gdrive:training/syncswim/"
    rsync:   "user@nas.local:/srv/syncswim/"
             "/Volumes/External/syncswim/"   (local USB drive)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_DATA = _ROOT / "data"
DEFAULT_LOG = DEFAULT_DATA / ".backup.log"
DEFAULT_TARGET_FILE = DEFAULT_DATA / ".backup_target"


def _log(msg: str, log_path: Path) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")
    except OSError:
        # Logging failure is itself non-fatal — better to lose a log
        # line than crash the backup.
        pass


def _resolve_target(args: argparse.Namespace) -> str | None:
    if args.target:
        return args.target.strip()
    env = os.environ.get("BACKUP_TARGET", "").strip()
    if env:
        return env
    if DEFAULT_TARGET_FILE.exists():
        try:
            first = DEFAULT_TARGET_FILE.read_text().strip().splitlines()
            if first and first[0].strip():
                return first[0].strip()
        except OSError:
            pass
    return None


def _classify(target: str) -> str:
    """Decide rsync vs rclone backend.

    rsync targets are absolute paths or look like ``user@host:/path``.
    Everything else is treated as an rclone remote — but we still
    fall back to rsync if rclone isn't installed (so a typo'd
    "rclone-style" target still has a chance of working as a local
    rsync path).
    """
    head, _, _ = target.partition(":")
    if target.startswith("/") or "@" in head:
        return "rsync"
    if shutil.which("rclone"):
        return "rclone"
    if shutil.which("rsync"):
        return "rsync"
    return "none"


def _run_rsync(src: Path, dst: str, log_path: Path) -> bool:
    # ``--delete-after`` mirrors src exactly but defers deletes until
    # after the transfer succeeds — partial-transfer failures don't
    # eat data on the destination.
    # ``--partial`` keeps half-transferred files so a flaky network
    # can resume next run instead of restarting from zero.
    cmd = [
        "rsync", "-a", "--delete-after", "--partial",
        "--exclude=.backup.log", "--exclude=.backup_target",
        f"{src}/", dst,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=3600)
    except FileNotFoundError:
        _log("[error] rsync not installed", log_path)
        return False
    except subprocess.TimeoutExpired:
        _log("[error] rsync timed out (>1h)", log_path)
        return False
    if result.returncode == 0:
        _log(f"[ok] rsync → {dst}", log_path)
        return True
    err = result.stderr.decode(errors="ignore").strip()[:200]
    _log(f"[fail] rsync rc={result.returncode}: {err}", log_path)
    return False


def _run_rclone(src: Path, dst: str, log_path: Path) -> bool:
    cmd = [
        "rclone", "sync", str(src), dst,
        "--exclude", ".backup.log",
        "--exclude", ".backup_target",
        "--transfers=4",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=3600)
    except FileNotFoundError:
        _log("[error] rclone not installed", log_path)
        return False
    except subprocess.TimeoutExpired:
        _log("[error] rclone timed out (>1h)", log_path)
        return False
    if result.returncode == 0:
        _log(f"[ok] rclone → {dst}", log_path)
        return True
    err = result.stderr.decode(errors="ignore").strip()[:200]
    _log(f"[fail] rclone rc={result.returncode}: {err}", log_path)
    return False


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--src", type=Path, default=DEFAULT_DATA,
                        help="Source directory (default: data/)")
    parser.add_argument("--target", default=None,
                        help="Backup target (overrides env / .backup_target)")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG,
                        help="Log file path (default: data/.backup.log)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print resolved target + backend, don't sync")
    args = parser.parse_args()

    if not args.src.exists():
        _log(f"[error] src does not exist: {args.src}", args.log)
        sys.exit(0)   # never crash cron

    target = _resolve_target(args)
    if not target:
        _log("[skip] no target configured "
             "(use --target / env BACKUP_TARGET / data/.backup_target)",
             args.log)
        sys.exit(0)

    backend = _classify(target)
    if backend == "none":
        _log("[error] neither rclone nor rsync is installed", args.log)
        sys.exit(0)

    if args.dry_run:
        print(f"[dry-run] would use {backend} to sync {args.src}/ → {target}")
        sys.exit(0)

    runner = _run_rsync if backend == "rsync" else _run_rclone
    runner(args.src, target, args.log)
    # Always exit 0 — the log captures success/failure, and cron
    # sending an email every 15 minutes from a transient sync failure
    # is far more painful than silently retrying next tick.
    sys.exit(0)


if __name__ == "__main__":
    main()
