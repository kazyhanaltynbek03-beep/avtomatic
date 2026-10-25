# Route, page and interactive-control inventory

The SPA uses hash navigation. Every route below is permission-gated by the shared
`can()` helper and renders loading, empty and API-error states through the common
feedback components.

| Route | Page | Backend source / action |
|---|---|---|
| `#dashboard`, `#analytics`, `#profit` | Overview and finance analysis | `/report`, `/dashboard/summary`, `/report/details` |
| `#forecast`, `#alerts` | Forecast and alerts | `/forecast`, `/alerts` |
| `#products`, `#purchases`, `#batches`, `#stock`, `#movements` | Catalogue and inventory | `/data/*`, `/stock`, posting endpoints |
| `#sales`, `#Kaspi`, `#Wildberries`, `#Ozon`, `#Offline`, `#B2B`, `#customers` | Sales and channels | `/data/sales`, `/data/customers`, immutable posting endpoints |
| `#expenses`, `#cash`, `#accounting` | Finance and cash flow | `/data/expenses`, `/data/cash`, `/accounting/summary` |
| `#assistant`, `#content`, `#designer` | AI workspace | `/ai/*`, `/jobs` (AI only) |
| `#niches`, `#calculator` | Market observations and deterministic calculator | `/data/niches`, `/calculator` |
| `#companies`, `#accounts`, `#documents`, `#generated_documents` | Administration and documents | `/data/*`, account credential and sync endpoints |
| `#imports` | CSV/XLSX import | `/import/fields`, `/import/parse`, `/import/preview`, `/import/{id}/confirm` |
| `#users`, `#roles`, `#audit`, `#settings` | Access, audit and settings | `/data/users`, `/roles`, `/data/audit`, `/settings` |

## Interactive controls

* Navigation, mobile menu, range filters, refresh, tables, search, pagination and
  modal close controls have explicit state handlers.
* Create/edit/delete controls are shown only with write permission; delete always
  asks for confirmation and returns an inline API error on failure.
* Import controls follow parse → mapping → preview → confirm and disable while a
  request is active.
* Marketplace controls use `credentials → test connection → sync`; sync does not
  call `/api/jobs` and results are reported in the toast/error surface.
* AI write plans require explicit confirm/cancel actions. AI failures stay inside
  the AI surface and do not affect financial pages.
* Download controls are real links to protected backend exports/documents. Form
  submission buttons are inside their corresponding forms; there are no visual
  action buttons with empty handlers.
