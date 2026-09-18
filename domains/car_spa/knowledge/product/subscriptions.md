# Subscriptions & multipack (Car Spa Plus)

## Live multipack (current product)

| Field | Rule |
|-------|------|
| Offer | **Buy 5, get 6** washes (**5+1**) |
| SKU | `full_spa_premium_6_multipack` |
| Price (has last booking) | **Full Spa Premium** for that booking’s car **tier × 5** |
| Price (no prior booking) | **Full Spa Premium for T5 × 5** (`tier.id` = 8) |
| Redemptions | **Any** spa plan (Premium / Basic / Exterior), **up to 6** bookings |
| Car on redeem | **Any tier** car allowed while subscription is active |
| Concurrent packs | **No** — not more than one active multipack |
| Validity | **365 days** from purchase |

```text
P = Premium tier price(last booking car)
    or Premium tier price(T5) if no prior booking
multipack_total = P × 5
→ 6 spa bookings (any plan, any car tier) within 1 year
```

Constants: `subscription_constants.go` (`TotalWashes=6`, `PriceMultiplier=5`, `ValidityDays=365`).

## Measured redemption (2026-08-14)

125 real packs sold since June. **Only 24.3% of entitled washes have been redeemed**, and **77% of packs have used exactly one wash** — the one bundled into the purchase order. Just **24%** of packs have ever seen a second visit, and no pack has used more than 3 of its 5–6 washes.

496 washes (~₹228,000 of service) sit unredeemed. Since unused washes expire with **no refund**, the pack currently behaves as a **first-wash discount** rather than a six-wash commitment.

Full cohort table and the commercial reading: [../business/metrics.md](../business/metrics.md#subscriptions--bought-barely-used).

## Retired multipack (still honoured)

`full_spa_premium_5_multipack` — the old **4+1** (buy 4, get 5, tier × 4) — stays in
`SubscriptionSKUConfigs` with `Purchasable: false`. It is never offered for sale, but is still
a fully valid SKU for pricing, fulfilment, listing and redemption, so packs sold before the
switch behave exactly as they did at purchase.

Entitlement is safe by construction: `total_washes` is stamped onto the `car_wash_subscriptions`
row at fulfilment from the SKU the order was placed with, and every read uses the stored value.
Existing 4+1 holders keep 5 washes; no migration, no backfill.

### Adding or retiring a pack

1. Add the SKU constant and its `SubscriptionSKUConfig` (`Purchasable: true`).
2. Flip the outgoing pack to `Purchasable: false` — leave its config untouched.
3. Put the new SKU first in `subscriptionSKUOrder`.
4. Register the SKU in the order/catalog service **before** deploying.

Offer copy needs no edits: `RenderSubscriptionOfferCopy` resolves `{paid}` / `{free}` /
`{total}` / `{pack}` against the purchasable SKU, and every user-facing string
(`plan_pack_offer_constants.go`, `subscription_page_data_constants.go`, the listing FAQ, the
home-page promo banner) is templated on it.

## Pack badge on booking details

`GET /car-care/bookings/:bookingID/details` returns `subscription_badge` — `"4+1 Car Spa
Premium"` or `"5+1 Car Spa Premium"` — naming the pack that booking was redeemed against.
Omitted entirely for bookings paid for normally, so the app just hides the chip.

Details is the **only** endpoint carrying it: not the bookings listing, not `POST /carts`.

The badge resolves through the booking's own `car_wash_subscription_usages` row →
subscription → SKU, **not** the user's current pack. Someone who exhausted a 4+1 and then
bought a 5+1 still sees `4+1` on the older bookings.
`ListCarWashSubscriptionSKUsByBookingIDs` deliberately does not filter the subscription on
`is_active`/`status`: which pack funded a completed booking stays true after that pack expires
or is exhausted.

`SubscriptionPackBadgeForSKU` renders per-SKU via `SubscriptionSKUConfig.RenderOfferCopy`, so
the badge never describes the pack currently on sale. The db_manager helper takes a slice of
booking IDs, so extending this to the listing later is wiring, not a new query.

## Upsell after a one-time spa

- Cron: `send-subscription-upsell-notifications`
- Users without active subscription, ≈ **3 days** after booking
- WhatsApp `CAR_WASH_SUBSCRIPTION_UPSELL` + deeplink (`show_subscription=true`)

## Statuses

`PENDING` → `ACTIVE` → `EXPIRED` / `EXHAUSTED` / `CANCELLED` / `FAILED`

## Engineering map

| Concern | Start |
|---------|--------|
| Pack offers | `plan_pack_offers_controller.go`, `plan_pack_offers_presentation.go` |
| Price resolve | `subscription_multipack.go` |
| Validate / list | `subscription_controller.go`, `subscription_listing_page.go` |
| Fulfilment / usage | `subscription_fulfilment_controller.go`, `subscription_usage_controller.go` |
| DB | `db_manager/car_wash_subscription_helper.go` |
