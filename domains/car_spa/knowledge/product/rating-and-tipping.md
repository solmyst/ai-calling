# Rating & tipping

## Rating

- Post-job WhatsApp nudge via `send-completed-rating-notifications`.
- Timing (code): slot ended ≥ **45 minutes** ago; cron ~15 min interval.
- Meta flag: `completed_rating_notification_sent`.
- APIs: `rating_controller.go`, `rating_config.go`.

## Tipping (live)

Optional tip after service via OMS tipping category → Kafka `kafkaconsumers/car_wash_tipping/` → `order_tipping`.

| Amount (₹) | SKU |
|------------|-----|
| 30 | `tipping_20` |
| 50 | `tipping_30` |
| 100 | `tipping_50` |

## Settlement

- Tip row stores **`cleaner_id` + amount** on `order_tipping` after Kafka consume.
- **Who ultimately receives the money (cleaner salary vs Park+):** not documented in this repo — see [../questions.md](../questions.md) R-03b.

## Notes

- Tips ≠ refunds. Refunds are full + manual via OMS when raised.
