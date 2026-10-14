# Unpaid order reminder

One Telegram message to a signed-in buyer whose order expired before it was
paid, with a «Купить снова» button that opens the brand's page in the Mini App.

- Code: `apps/api/src/yupay/modules/orders/unpaid_reminder.py`, job
  `orders.remind_unpaid` (every 5 minutes, `apps/scheduler/.../jobs/unpaid_reminder.py`).
- Switch: `UNPAID_REMINDER_AFTER_MINUTES` in `api.env`, read by the scheduler.
  Default 20 (on); `0` turns it off. Restart the scheduler with the deployed
  `IMAGE_TAG` after changing it.

## Who gets it

- Retail catalog orders of a signed-in user with a linked Telegram. Guests and
  resellers never.
- Status `expired`, created between 20 minutes and 3 hours ago.
- Not when the same user made a later order that was paid or is awaiting
  payment.
- One order per user per run (the newest); nothing to the same user for 24
  hours after a reminder.

Every selected order gets an `order.unpaid_reminder_sent` event in
`order_events` (`payload.delivered` false when there was no chat to send to),
so it is never selected again.

## Is it working

```sql
select date_trunc('day', e.created_at) d,
       count(*) filter (where (e.payload->>'delivered')::bool) sent,
       count(*) filter (where (e.payload->>'delivered')::bool and exists (
         select 1 from orders o2 join orders o on o.id = e.order_id
         where o2.user_id = o.user_id and o2.paid_at is not null
           and o2.created_at > e.created_at
           and o2.created_at < e.created_at + interval '24 hours')) bought_after
from order_events e
where e.kind = 'order.unpaid_reminder_sent'
group by 1 order by 1 desc limit 14;
```

`bought_after / sent` is the return rate. Baseline before the reminder
(30 days to 2026-10-14): 1225 expired retail orders, 416 of them followed by a
paid order from the same buyer within 24 hours.

## Complaints

A buyer who finds it annoying: set the switch to `0` and restart the
scheduler. There is no per-user opt-out yet.
