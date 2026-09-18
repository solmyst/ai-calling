# Notifications (documented)

**Purpose:** Customer/ops notification triggers grounded in this service’s code.  
**Last updated:** 2026-07-15  
**Status:** Populated (channels from constants)  
**Owner:** Product · Engineering  
**Related:** [rating-and-tipping.md](rating-and-tipping.md) · [../engineering/services.md](../engineering/services.md) · [../integrations/notification.md](../integrations/notification.md)

## Channels (code)

| Medium | Constant | Used? |
|--------|----------|-------|
| App notification | `app_notification` | Yes — default list with WhatsApp for most lifecycle events |
| WhatsApp | `whatsapp` | Yes — always for reschedule; with app for others |
| SMS | — | **Not** in `CarWashNotificationMediumList` |
| Email | — | **Not** used as a Car Spa notify medium in this repo |
| Slack | Slack webhooks | Ops only (cleaner late, etc.) |

Default list: `CarWashNotificationMediumList` in `config/constants/constants.go`.

## Customer / ops triggers

| Trigger | Channel(s) | Recipient | Code / cron |
|---------|------------|-----------|-------------|
| Expert assigned / will arrive | app + WhatsApp (assignment alert path) | Customer | `SendExpertAssignedNotification` |
| Cleaner reached (+ start pin as verification_code) | lifecycle medium list | Customer | `SendCleanerReachedNotification` |
| Reassurance ~2h before slot | lifecycle medium list | Customer | `ScheduleReassurance2HrBeforeNotification` |
| Cleaner late (>30m after slot, booking **ASSIGNED**) | medium list + Slack | Customer + Ops | `SendCleanerLateNotification`, cron `send-cleaner-late-notifications` |
| Booking rescheduled | **WhatsApp only** | Customer | `SendBookingRescheduledNotification` |
| Rating nudge | ~45m after slot end | Customer | cron `send-completed-rating-notifications` |
| Subscription / multipack upsell | ~day 3 if no active sub | Customer | cron `send-subscription-upsell-notifications` |

## Related

- [error-states.md](error-states.md) · [../operations/assignment.md](../operations/assignment.md)
