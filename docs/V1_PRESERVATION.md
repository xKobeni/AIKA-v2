# AIKA V1 preservation

## Read-only inventory

| Item | Finding |
| --- | --- |
| Checkout | `C:\Users\johna\OneDrive\Documents\Visual Studio Blue\AIKA AI` |
| Git revision | `ff5eacc3cc7489a0fef82a6ff1ed1558b70ecabf` on `fix/core-reliability`. The checkout has existing changes, deletions, and untracked files. |
| Database | V1 documents PostgreSQL with pgvector. The checkout's `.env` points to `localhost:5432`. Its parsed database field contains whitespace. `SETUP.md` names `AIKA_DB` in its setup example. Confirm the effective database name privately before taking a dump. |
| Existing backup files | Three `.dump` files were found under V1 `backups/`. Contents, currency, completeness, and recoverability are pending verification. |
| Live status | V1 startup, database connectivity, and live schema version are pending verification. |

Review the scoped memory and correction tests in `tests/test_phase9d_memory_accuracy.py` and `tests/test_phase9j1_memory_integration.py`, tool-policy cases in `tests/test_phase2_tool_security.py`, and redaction behavior in `src/security/redaction.py` as references for future checkpoints. Character portraits and expression artwork remain in the recorded Git revision under `aika-subtle-anime-prototype/assets/`. Those tracked prototype files were already deleted in the working tree at inspection. Review reuse separately.

## Backup and recovery procedure

1. Make a private copy of the entire V1 checkout in independent storage, including `.git`, current tracked changes, untracked work, and required local configuration. Secure secrets and personal data in that copy. Record the branch, revision, and working-tree status so recovery includes work beyond the commit.
2. Confirm the effective PostgreSQL host, port, database, and backup role from V1's configuration. Use a compatible `pg_dump` client and the appropriate secure authentication prompt or PostgreSQL password file. Export the complete source database with `pg_dump --format=custom --host <v1-host> --port <v1-port> --username <backup-role> --dbname <v1-database> --file <new-private-dump>`. Record server and pgvector versions plus any roles or grants needed for recovery. Check the exit code, list the archive with `pg_restore --list`, and retain its SHA-256 hash with the backup. [PostgreSQL backup documentation](https://www.postgresql.org/docs/current/backup-dump.html)
3. Test recovery from a trusted copy in an isolated PostgreSQL instance with compatible pgvector support. Create a new, empty recovery database from `template0` and provision required roles. Verify the destination before running `pg_restore --single-transaction --exit-on-error --host <recovery-host> --port <recovery-port> --username <restore-role> --dbname <recovery-database> <private-dump>`. Check schema and migration version, key table counts, and representative reads. If testing V1 startup, use a separate checkout copy configured only for that restored database. [PostgreSQL restore documentation](https://www.postgresql.org/docs/current/app-pgrestore.html)

## Manual preservation checklist

- [ ] Confirm the effective database name and record its live schema version without exposing credentials.
- [ ] Verify a current independent copy of V1 source, working files, configuration, and database backup.
- [ ] Confirm V1 is recoverable through an isolated restore or use an existing known-good V1 installation without changing it.

Phase 0A inspected V1 files read-only. Database access, the backup procedure, and the recovery drill are pending. V2 will use its own SQLite database, introduced in Phase 1C.
