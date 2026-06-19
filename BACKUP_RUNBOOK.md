# Backup Runbook

## How the backup works

The backup script uses SQLite's `VACUUM INTO` command to create a safe, transactionally consistent copy of the live database.

Why this is used:
- It asks SQLite itself to write the backup.
- It avoids the unsafe plain file-copy pattern for a live `.db` file.
- It produces a standalone backup file in `backups/` with a timestamped name like `app_2026-06-19_03-00.db`.

The script also:
- writes a simple success/failure log entry to `backups/backup.log`
- deletes backups older than 14 days so disk usage stays bounded

## How to create a backup

Run from the project root:

```powershell
python scripts/backup_db.py
```

Optional environment variables:
- `DATABASE_URL`: use a specific SQLite database URL
- `BACKUP_DB_PATH`: override the database file path directly
- `BACKUP_DIR`: override the backup output directory
- `BACKUP_LOG_PATH`: override the log file path
- `BACKUP_RETENTION_DAYS`: override the 14-day retention window

## How to restore from a backup

1. Stop the app service so nothing is writing to the database.
2. Identify the backup file you want to restore from in `backups/`.
3. Make a precautionary copy of the current live database before replacing it.
4. Replace the live database file with the selected backup.
5. Start the app service again.
6. Open the dashboard and confirm login, inbox, and admin pages load normally.

Example flow on the server:

```powershell
sudo systemctl stop vip-catamaran
cp /opt/vip-catamaran/cruise_email_dashboard/app.db /opt/vip-catamaran/cruise_email_dashboard/app.db.pre-restore
cp /opt/vip-catamaran/backups/app_2026-06-19_03-00.db /opt/vip-catamaran/cruise_email_dashboard/app.db
sudo systemctl start vip-catamaran
```

Adjust the paths if the deployment directory differs.

## How to verify a backup before restoring

Before restoring, verify the backup is readable and structurally valid.

### Quick integrity check

```powershell
sqlite3 backups/app_2026-06-19_03-00.db "PRAGMA integrity_check;"
```

Expected result:

```text
ok
```

### Basic table check

```powershell
sqlite3 backups/app_2026-06-19_03-00.db ".tables"
```

Confirm that expected tables such as `users`, `emails_log`, `hotels`, and `bus_stops` are present.

### Optional row-count spot checks

```powershell
sqlite3 backups/app_2026-06-19_03-00.db "SELECT COUNT(*) FROM emails_log;"
sqlite3 backups/app_2026-06-19_03-00.db "SELECT COUNT(*) FROM users;"
```

Use these counts to sanity-check that the backup looks plausible before restoring it over the live database.
