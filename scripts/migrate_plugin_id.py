#!/usr/bin/env python3
"""Move a local StreamController install from one plugin id to another.

Renaming a plugin's package id breaks two things in an existing install: the
plugin folder name (the app derives the settings path from it) and the action
ids stored in the pages. This script does both, keeping a backup of every file
it rewrites. It is idempotent: running it twice does nothing the second time.

    python3 scripts/migrate_plugin_id.py --old com_example_old --new com_example_new --dry-run
    python3 scripts/migrate_plugin_id.py --old com_example_old --new com_example_new
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

DEFAULT_DATA = Path.home() / ".var" / "app" / "com.core447.StreamController" / "data"


class Migrator:
    def __init__(self, data: Path, old: str, new: str, dry_run: bool):
        self.data = data
        self.old = old
        self.new = new
        self.dry_run = dry_run
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self.backup_root = data / f"migration-backup-{self.stamp}"
        self.changes = 0
        self.backups = 0

    def say(self, message: str) -> None:
        print(("(dry run) " if self.dry_run else "") + message)

    def move_plugin_folder(self) -> None:
        old_path = self.data / "plugins" / self.old
        new_path = self.data / "plugins" / self.new
        if new_path.exists() or new_path.is_symlink():
            self.say(f"plugins/{self.new} already exists; leaving it alone")
            return
        if old_path.is_symlink():
            target = os.readlink(old_path)
            self.say(f"plugins/{self.old} -> {target}: rename to plugins/{self.new}")
            if not self.dry_run:
                os.symlink(target, new_path)
                old_path.unlink()
            self.changes += 1
        elif old_path.is_dir():
            self.say(f"plugins/{self.old}: rename directory to plugins/{self.new}")
            if not self.dry_run:
                old_path.rename(new_path)
            self.changes += 1
        else:
            self.say(f"plugins/{self.old} not found; nothing to rename")

    def copy_settings(self) -> None:
        source = self.data / "settings" / "plugins" / self.old / "settings.json"
        target = self.data / "settings" / "plugins" / self.new / "settings.json"
        if not source.is_file():
            self.say("no plugin settings to migrate")
            return
        if target.exists():
            self.say(f"settings/plugins/{self.new}/settings.json already exists; leaving it alone")
            return
        self.say(f"copy settings/plugins/{self.old}/settings.json -> settings/plugins/{self.new}/")
        if not self.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.changes += 1

    def rewrite_pages(self) -> None:
        roots = [self.data / "pages", self.data / "sticky"]
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.json")):
                if self.backup_root in path.parents:
                    continue
                try:
                    text = path.read_text()
                except OSError as exc:
                    print(f"skip {path}: {exc}", file=sys.stderr)
                    continue
                hits = text.count(self.old)
                if not hits:
                    continue
                self.say(f"{path.relative_to(self.data)}: {hits} action id(s) {self.old} -> {self.new}")
                if not self.dry_run:
                    backup = self.backup_root / path.relative_to(self.data)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, backup)
                    self.backups += 1
                    path.write_text(text.replace(self.old, self.new))
                self.changes += 1

    def run(self) -> int:
        if not self.data.is_dir():
            print(f"data directory not found: {self.data}", file=sys.stderr)
            return 2
        if self.old == self.new:
            print("old and new ids are the same", file=sys.stderr)
            return 2
        self.move_plugin_folder()
        self.copy_settings()
        self.rewrite_pages()
        if self.changes == 0:
            print("nothing to do")
            return 0
        if self.dry_run:
            print(f"\n{self.changes} change(s) would be made")
            return 0
        print(f"\n{self.changes} change(s) applied; {self.backups} file(s) backed up in {self.backup_root}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate a local install from one plugin id to another")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="StreamController data directory")
    parser.add_argument("--old", required=True, help="plugin id to migrate from")
    parser.add_argument("--new", required=True, help="plugin id to migrate to")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return Migrator(args.data.expanduser(), args.old, args.new, args.dry_run).run()


if __name__ == "__main__":
    raise SystemExit(main())
