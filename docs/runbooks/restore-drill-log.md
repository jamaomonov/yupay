# Restore drill log

Track quarterly restore drills (see `restore-from-backup.md`). Add a row per drill.

| Date (UTC) | Operator    | Backup used                                      | Outcome | Notes                                                                                                                                                                                                              |
| ---------- | ----------- | ------------------------------------------------ | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 2026-07-13 | @jamaomonov | `2026-07-13/yupay-2026-07-13T14-14-31Z.dump.age` | ✅ pass | Partial drill on first backup after the VPS move: pulled from R2, decrypted with the offline key, `pg_restore --list` showed 213 objects and every table. **Not** restored into a scratch DB — do that next drill. |
