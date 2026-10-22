# Push notifications (mobile app)

ADR-0102. Pushes go out of the worker's `push` queue through Expo. Receipts are read every 15
minutes by the scheduler job `push.check_receipts`.

## Is it working?

```sql
-- the last day, by outcome
SELECT status, receipt_status, count(*)
FROM push_messages
WHERE created_at > now() - interval '1 day'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- stuck: pending and due for more than 10 minutes
SELECT count(*) FROM push_messages
WHERE status = 'pending' AND next_attempt_at < now() - interval '10 minutes';

-- why the recent ones failed
SELECT last_error, count(*) FROM push_messages
WHERE status = 'failed' AND created_at > now() - interval '1 day'
GROUP BY 1 ORDER BY 2 DESC;
```

Loki: `{container="yupay-prod-worker-1"} |= "push."`. The events are `push.queued`,
`push.sent`, `push.send_unavailable`, `push.send_rejected`, `push.device.not_registered`
and `push.receipts_checked`.

## Failure modes

| Symptom                                              | Cause                                                                     | What to do                                                                            |
| ---------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Everything `skipped`                                 | `ENVIRONMENT` is not `prod`                                               | Expected outside prod                                                                 |
| `pending` piling up, `push.send_unavailable`         | Expo down, 429 or 5xx                                                     | Nothing: backoff retries, at most 6 attempts, then `failed`                           |
| `failed` with `http 401`/`403`, `push.send_rejected` | `EXPO_ACCESS_TOKEN` wrong or revoked while enhanced security is on        | Fix the token in `api.env` (the worker reads it), restart the worker with `IMAGE_TAG` |
| `failed` with `InvalidCredentials`                   | APNs key or FCM credentials missing or expired in the Expo project        | `eas credentials` for that platform                                                   |
| Many `DeviceNotRegistered`                           | Normal: app removed or token rotated                                      | The device is disabled automatically; the app re-registers at next launch             |
| Nothing queued for an order                          | Guest or merchant order, no active device, or a status that does not push | Check `push_devices` for the user (`disabled_at IS NULL`)                             |

## Turning it off

There is no flag. Pushes only come from devices the app registered. To stop them all at once,
stop draining:

```sql
UPDATE push_messages SET status = 'skipped' WHERE status = 'pending';
```

Then take the `push` queue out of the worker's `_queues` and deploy.
