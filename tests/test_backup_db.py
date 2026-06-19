from __future__ import annotations

from datetime import datetime, timedelta
import importlib.util
import os
import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path


def load_backup_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "backup_db.py"
    spec = importlib.util.spec_from_file_location("backup_db_script", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class BackupDbTests(unittest.TestCase):
    def test_sqlite_backup_uses_vacuum_into_and_prunes_old_backups(self) -> None:
        backup_db = load_backup_module()

        repo_tmp_root = Path(__file__).resolve().parents[1] / "tmp_test_backup"
        repo_tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_path = repo_tmp_root / f"case_{uuid.uuid4().hex}"
        try:
            tmp_path.mkdir(parents=True, exist_ok=True)
            db_path = tmp_path / "live.db"
            backups_dir = tmp_path / "backups"
            log_path = backups_dir / "backup.log"
            backups_dir.mkdir(parents=True, exist_ok=True)

            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("INSERT INTO sample (value) VALUES ('hello')")
                connection.commit()

            old_backup = backups_dir / "app_2026-05-01_03-00.db"
            old_backup.write_text("old backup", encoding="utf-8")
            old_time = (datetime(2026, 6, 19, 3, 0, 0) - timedelta(days=20)).timestamp()
            import os
            os.utime(old_backup, (old_time, old_time))

            now = datetime(2026, 6, 19, 3, 0, 0)
            created_backup = backup_db.create_sqlite_backup(
                db_path=db_path,
                backups_dir=backups_dir,
                log_path=log_path,
                now=now,
                retention_days=14,
            )

            self.assertTrue(created_backup.exists())
            self.assertEqual(created_backup.name, "app_2026-06-19_03-00.db")
            self.assertFalse(old_backup.exists())
            self.assertTrue(log_path.exists())

            with sqlite3.connect(created_backup) as backup_connection:
                row = backup_connection.execute("SELECT value FROM sample").fetchone()
            self.assertEqual(row[0], "hello")

            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("SUCCESS", log_text)
            self.assertIn(str(created_backup), log_text)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
