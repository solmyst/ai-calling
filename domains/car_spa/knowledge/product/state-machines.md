# State machines (index)

**Purpose:** Single entry for lifecycle/state docs — avoids LLM hunting across pages.  
**Last updated:** 2026-07-15  
**Status:** PARTIAL  
**Owner:** Product (Saurabh Mishra) · Backend (Mandeep / Ankur)

| Domain | Documented? | Primary doc | Notes |
|--------|-------------|-------------|-------|
| **Booking / job FSM** | ✅ | [../operations/booking-lifecycle.md](../operations/booking-lifecycle.md) | CREATED → … → COMPLETED terminals; cleaner app drives updates |
| **Order (OMS → booking)** | ⚠️ | [../engineering/system-design.md](../engineering/system-design.md) | Pay → Kafka → `car_wash_fulfilment` → CREATED; failure branches ❌ |
| **Order lifecycle (business)** | ⚠️ | [../operations/order-lifecycle.md](../operations/order-lifecycle.md) | Happy path only; status enum mapping TODO |
| **Subscription / multipack** | ✅ | [subscriptions.md](subscriptions.md) | PENDING → ACTIVE → EXPIRED / EXHAUSTED / CANCELLED / FAILED |
| **Payment** | ❌ | [../integrations/payment.md](../integrations/payment.md) | Stub |
| **Refund** | ⚠️ | [../operations/cancellations.md](../operations/cancellations.md), [../operations/refunds.md](../operations/refunds.md) | Full manual via OMS when raised; auto paths ❌ |
| **Rating** | ⚠️ | [rating-and-tipping.md](rating-and-tipping.md) | Post-job nudge; in-app/API flow partial |
| **Tip** | ⚠️ | [rating-and-tipping.md](rating-and-tipping.md) | OMS tip SKUs → Kafka consumer |

## Booking FSM (quick reference)

```text
CREATED → ASSIGNED → REACHED → STARTED → INTERIOR_COMPLETED → EXTERIOR_COMPLETED
  → CLEANED | DELIVERY_ITEMS_ACKNOWLEDGED | COMPLETED
```

Also: `REASSIGNED`, `CANCELLED`, `SKIPPED` — see booking-lifecycle doc.

## Related

- [customer-journey.md](customer-journey.md) · [../engineering/system-design.md](../engineering/system-design.md) · [../data/enums/catalog.md](../data/enums/catalog.md)
