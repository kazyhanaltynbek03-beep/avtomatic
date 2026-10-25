# Public competitor research

This summarizes only public product statements checked on 2026-10-09; it does not infer private implementation details.

| Service | Publicly stated behavior | Useful design principle for QOR |
|---|---|---|
| MPSTATS | Its knowledge base says weekly WB reports are a core source for its seller finance reports, that the service imports those reports via seller API, and that report values can differ or be corrected later. The same article says its separate “Finances” module no longer operates (article updated 2026-01-19). | Show source, period, last refresh, and correction/reconciliation state; do not silently replace settled history. |
| Маяк | Public product pages advertise financial analytics alongside sales, product, logistics, and supply analytics. | Keep financial reporting distinct from market/competitor estimates. |
| Moneyplace | Public pages advertise seller analytics, dashboards, and unit economics. Public pages reviewed do not document exact weekly report ingestion or accounting formulas. | Do not claim equivalence based on marketing pages; establish field definitions and source lineage inside QOR. |

Sources:

- MPSTATS finance data and comparison article: <https://wiki.mpstats.io/FAQ/%D0%9E%D1%82%D1%87%D0%B5%D1%82%D1%8B/%D0%9A%D0%B0%D0%BA_%D1%81%D0%BE%D0%B1%D0%B8%D1%80%D0%B0%D0%B5%D0%BC_%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D0%B5_%D0%B8_%D0%BA%D0%B0%D0%BA_%D0%B8%D1%85_%D1%81%D1%80%D0%B0%D0%B2%D0%BD%D0%B8%D0%B2%D0%B0%D1%82%D1%8C>
- Mayak: <https://mayak.bz/>
- Moneyplace: <https://moneyplace.io/>
