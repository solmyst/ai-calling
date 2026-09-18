# Service catalog

**Purpose:** Human-readable inclusions by package + canonical item IDs.  
**Last updated:** 2026-07-14  
**Status:** Populated  
**Source:** App UI + `plan_services` + plan metadata

Atomic line items that compose plans. `meta_data.service_id` is the stable string key.

## Canonical item map (`plan_services` / item_id)

| id | Name | Duration (mins) | Type | Tag | service_id | Catalog original_price* |
|----|------|-----------------|------|-----|------------|-------------------------|
| 1 | Foam Wash | 20 | exterior | Standard Inclusions | `foam_wash` | 99 |
| 2 | Tyre Cleaning & Polish | 5 | exterior | Only on Park+ | `tyre_cleaning` | 49 |
| 3 | Tyre Polish | 5 | exterior | Only on Park+ | `tyre_polish` | — |
| 4 | Exterior Wax | 10 | exterior | Only on Park+ | `exterior_wax` | 149 |
| 5 | Glass Cleaning | 5 | exterior | Standard Inclusions | `glass_cleaning` | 49 |
| 6 | Vacuum Cleaning | 10 | interior | Standard Inclusions | `vacuum_cleaning` | 99 |
| 7 | Dashboard & Interior Wipe | 10 | interior | Standard Inclusions | `dashboard_wipe` | — |
| 8 | Seat Cleaning | 5 | interior | Standard Inclusions | `seat_cleaning_and_sanitization` | 129 |
| 9 | Dashboard Interior Polish & Wipe | 10 | interior | Standard Inclusions | `dashboard_and_interior_polish` | 149 |
| 10 | Cladding Cleaning & Polish | 20 | exterior | Only on Park+ | `plastic_cladding_cleaning_and_polish` | 199 |
| 11 | Interior Deep Cleaning | 10 | interior | Only on Park+ | `deep_interior_detailing` | 199 |

\* `meta_data.original_price` on the service row — marketing/list reference, **not** the live sell price. Live sell = `plan_item_tier_pricing.discounted_price` for plan + tier.

Note: App cards sometimes collapse tyre / dashboard steps; backend may keep separate ids (2/3, 7/9). Prefer **active** catalog rows for customer-facing lists; tier pricing may still reference component ids used in sum examples.

## Plan membership (product)

| Plan | Typical services (ids) |
|------|------------------------|
| Exterior Only (3) | 1, 2, 4, 5 (+ marketing steps like tyre polish / glass as listed in plan meta) |
| Full Car Spa Basic (2) | Exterior set + 6, 8, 9 (and wipe/polish steps per plan meta) |
| Full Car Spa Premium (1) | Basic + 10, 11 |

See [plans.md](plans.md) for minute breakdowns from plan meta.

## Addons

**Disabled for all plans** (not offered to customers). Do not surface addons in product UX or pricing docs.

## Common exclusions (customer-facing)

- Seat dry-cleaning, deep stain removal, inner roof cleaning
- Bonnet (engine bay) and underbody cleaning
- Pet hair removal, biohazard cleanup, surrounding floor water cleanup

## Video proof constraints

Plan item pricing meta commonly includes `min_video_length`: 15, `max_video_length`: 60.

## Engineering

- Model: `PlanServiceCatalog` → table `plan_services`
- Controllers load catalog via `db_manager` + tier helpers (`tier_catalog_helper.go`, plan controllers)
