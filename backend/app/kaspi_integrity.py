"""Evidence for API coverage; missing event dates are never guessed."""
from datetime import datetime
from zoneinfo import ZoneInfo
from math import isfinite

SCAN_VERSION = 3


def period_key(mode, start, end):
    return f"{mode}-complete-v{SCAN_VERSION}:{start}:{end}"


def source_quality(accounts, rows, start, end):
    orders, entries = {}, {}
    issues = {"missing_entries": 0, "missing_completion_date": 0,
              "missing_return_date": 0, "invalid_lines": 0,
              "missing_product_identity": 0, "orphan_entries": 0}
    for account_id, payload in rows:
        p = payload or {}
        key = (account_id, str(p.get("order_id") or ""))
        if p.get("record_type") == "order":
            orders[key] = p
        elif p.get("record_type") == "order_entry":
            entries.setdefault(key, []).append(p)
    for key, order in orders.items():
        status = str(order.get("status") or "").upper()
        if status not in {"COMPLETED", "RETURNED"}:
            continue
        # An unknown date could belong to any requested period.
        completion = order.get("completion_date")
        try:
            day = datetime.fromtimestamp(float(completion) / 1000, ZoneInfo("Asia/Almaty")).date()
        except (TypeError, ValueError, OverflowError, OSError):
            day = None
        if day is None:
            issues["missing_completion_date"] += 1
        if status == "RETURNED" and not order.get("returned_date"):
            issues["missing_return_date"] += 1
        if day is not None and not start <= day <= end and status != "RETURNED":
            continue
        lines = entries.get(key, [])
        expected = order.get("entries_count")
        if not lines or order.get("entries_complete") is not True or (expected is not None and len(lines) != expected):
            issues["missing_entries"] += 1
        for line in lines:
            if not (line.get("sku") or line.get("external_product_id")):
                issues["missing_product_identity"] += 1
            try:
                quantity, amount = float(line.get("quantity")), float(line.get("total_price"))
                if not isfinite(quantity) or not isfinite(amount) or quantity <= 0 or amount < 0:
                    raise ValueError
            except (TypeError, ValueError):
                issues["invalid_lines"] += 1
    issues["orphan_entries"] = sum(len(lines) for key, lines in entries.items() if key not in orders)
    coverage = []
    progress = []
    for account in accounts:
        settings = account.integration_settings or {}
        proof = (settings.get("kaspi_period_sync") or {}).get(period_key("issued", start, end))
        coverage.append(bool(proof))
        job = settings.get("kaspi_period_job") or {}
        progress.append({"account_id": account.id, "status": job.get("status", "not_requested"),
                         "start": job.get("start"), "end": job.get("end"),
                         "batches": job.get("batches", 0), "records": job.get("records", 0),
                         "scan_from": job.get("scan_from"), "scan_through": job.get("scan_through"),
                         "state": job.get("state"), "page": job.get("page", 0)})
    return {"coverage_complete": bool(accounts) and all(coverage),
            "issues": issues, "progress": progress,
            "data_complete": not any(issues.values())}
