"""All amounts are integer minor units. Posted events are immutable.
FIFO locks the product row first, then batches, to prevent concurrent overselling.
A single physical warehouse contains separately owned legal-entity batches.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from decimal import InvalidOperation
from sqlalchemy import select, func, case
from fastapi import HTTPException
from .models import *
from .security import scope, scope_query, audit, scope_product


def fail(message):
    raise HTTPException(422, message)


def rounded(numerator, denominator):
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )




def kaspi_commission_estimates(db, user, start, end, company_id, account_id, sales, expenses, accounts):
    """Return estimated Kaspi fees by (account_id, order day), without booking cash.

    Only completed API order entries qualify. An explicit fee on the same seller/day
    takes precedence. If fees are present elsewhere in the selected period, unlinked
    estimates are suppressed and a reconciliation warning is returned.
    """
    import os
    from . import marketplace_pipeline

    raw_rate = os.getenv("KASPI_COMMISSION_RATE")
    if raw_rate in (None, ""):
        return {}, None, False
    try:
        rate = Decimal(str(raw_rate))
        if not rate.is_finite() or rate < 0 or rate > 1:
            raise ValueError
    except (ValueError, TypeError):
        return {}, None, False
    bps = int(rate * 10000)
    actual_days = {
        (e.account_id, e.date) for e in expenses
        if e.category in {"Marketplace commission", "Marketplace commission VAT"}
    }
    actual_days.update((sale.account_id, sale.date) for sale in sales if sale.commission > 0)
    # Explicit Kaspi fee rows may be dated on settlement/reporting day, while
    # order entries use completion day. Avoid adding unlinked estimates as if
    # they were a second confirmed fee when actual fees exist in the period.
    actual_period_accounts = {
        e.account_id for e in expenses
        if e.account_id and e.category in {"Marketplace commission", "Marketplace commission VAT"}
    }
    actual_period_accounts.update(sale.account_id for sale in sales if sale.commission > 0)

    account_ids = [a.id for a in accounts.values() if a.channel == "Kaspi"]
    if account_id:
        account_ids = [id_ for id_ in account_ids if id_ == account_id]
    bases = defaultdict(int)
    if account_ids:
        q = scope_query(select(MarketplaceRecord), MarketplaceRecord, user).where(
            MarketplaceRecord.account_id.in_(account_ids),
            MarketplaceRecord.source == "kaspi",
            func.lower(MarketplaceRecord.payload["record_type"].as_string()) == "order_entry",
            func.upper(MarketplaceRecord.payload["order_status"].as_string()) == "COMPLETED",
        )
        if company_id:
            q = q.where(MarketplaceRecord.company_id == company_id)
        for raw in db.scalars(q):
            if raw.reason_code == "DUPLICATE_EVENT":
                continue
            p = raw.payload or {}
            if str(p.get("record_type") or "").lower() != "order_entry":
                continue
            if str(p.get("order_status") or "").upper() != "COMPLETED":
                continue
            try:
                day = marketplace_pipeline._day(p.get("completed_date"), "Asia/Almaty")
                if not start <= day <= end:
                    continue
                base = marketplace_pipeline._cents(p.get("total_price"), accounts[raw.account_id], "KZT", db, day)
            except (marketplace_pipeline.Pending, InvalidOperation, TypeError, ValueError):
                continue
            bases[(raw.account_id, day)] += max(0, base)

    estimates = {}
    suppressed = False
    for key, base in bases.items():
        if key in actual_days:
            continue
        amount = (base * bps + 5000) // 10000
        if key[0] in actual_period_accounts:
            suppressed = suppressed or amount > 0
            continue
        estimates[key] = amount
    return estimates, str(rate), suppressed


def get_company(db, user, cid):
    scope(user, cid)
    c = db.scalar(select(Company).where(Company.id == cid).with_for_update())
    if not c or not c.active:
        fail("Компания не найдена или отключена")


def lock_product(db, pid):
    product = db.scalar(select(Product).where(Product.id == pid).with_for_update())
    if not product or not product.active:
        fail("Товар не найден или отключён")
    return product


def check_date(db, cid, d):
    # Backdated physical stock events would invalidate FIFO and historical stock.
    last = db.scalar(select(func.max(Movement.date)).where(Movement.company_id == cid))
    if last and d < last:
        fail(f"Склад уже проведён на {last}; используйте эту или более позднюю дату")


def check_account(db, cid, aid):
    a = db.get(Account, aid)
    if not a or a.company_id != cid:
        fail("Канал не принадлежит выбранной компании")
    return a


def cash_entry(db, **kw):
    if kw["amount"]:
        db.add(CashEntry(**kw))


def purchase(db, user, p):
    get_company(db, user, p.company_id)
    for pid in sorted(set(x.product_id for x in p.lines)):
        scope_product(db, user, pid, p.company_id)
        lock_product(db, pid)
    check_date(db, p.company_id, p.date)
    # Purchase lines may use a supplier currency. Convert once at posting time
    # and keep the resulting KZT tiyn in the batch/FIFO ledger.
    line_base_costs = [
        rounded(line.quantity * line.unit_cost * line.fx_rate, 10000)
        for line in p.lines
    ]
    base = sum(line_base_costs)
    breakdown_total = sum(p.cost_breakdown.values())
    if any(v < 0 for v in p.cost_breakdown.values()):
        fail("Компоненты Full Cost не могут быть отрицательными")
    if p.cost_breakdown and p.extra_cost and breakdown_total != p.extra_cost:
        fail("Сумма компонентов Full Cost должна совпадать с extra_cost")
    extra_cost = breakdown_total if p.cost_breakdown else p.extra_cost
    total = base + extra_cost
    if p.paid > total:
        fail("Оплата больше стоимости закупки")

    products = {x.product_id: db.get(Product, x.product_id) for x in p.lines}
    def allocation_weight(index, line):
        if p.allocation_method == "quantity":
            return line.quantity
        if p.allocation_method == "value":
            return line_base_costs[index]
        product = products[line.product_id]
        unit = product.weight_g if p.allocation_method == "weight" else product.volume_cm3
        if unit <= 0:
            fail(f"Для распределения по {p.allocation_method} заполните вес/объём всех товаров")
        return line.quantity * unit

    weights = [allocation_weight(i, line) for i, line in enumerate(p.lines)]
    denominator = sum(weights)
    if extra_cost and denominator <= 0:
        fail("Невозможно распределить дополнительные расходы: база распределения равна нулю")
    obj = Purchase(
        company_id=p.company_id,
        reference=p.reference,
        supplier=p.supplier,
        date=p.date,
        total=total,
        extra_cost=extra_cost,
        cost_breakdown=p.cost_breakdown,
        allocation_method=p.allocation_method,
    )
    db.add(obj)
    db.flush()
    extra_left = extra_cost
    for i, line in enumerate(p.lines):
        share = (
            extra_left
            if i == len(p.lines) - 1
            else (extra_cost * weights[i] // denominator if denominator else 0)
        )
        extra_left -= share
        cost = line_base_costs[i] + share
        b = Batch(
            company_id=p.company_id,
            product_id=line.product_id,
            purchase_id=obj.id,
            date=p.date,
            quantity=line.quantity,
            remaining=line.quantity,
            total_cost=cost,
            remaining_cost=cost,
        )
        db.add(b)
        db.flush()
        db.add(
            Movement(
                company_id=p.company_id,
                product_id=line.product_id,
                batch_id=b.id,
                date=p.date,
                quantity=line.quantity,
                cost=cost,
                kind="purchase",
                reference=p.reference,
            )
        )
    cash_entry(
        db,
        company_id=p.company_id,
        purchase_id=obj.id,
        reference="purchase:" + p.reference,
        date=p.date,
        amount=-p.paid,
        category="Закупка",
        description=p.supplier,
    )
    audit(
        db,
        user,
        "post",
        "purchases",
        obj.id,
        {
            "currency_lines": [
                {"product_id": x.product_id, "currency": x.currency, "fx_rate": x.fx_rate}
                for x in p.lines
            ]
        },
    )
    db.flush()
    reconcile_pending_cogs(db,user,p.company_id,[x.product_id for x in p.lines])
    return obj


def take_fifo(db, cid, pid, quantity, d, allow_partial=False):
    batches = db.scalars(
        select(Batch)
        .where(
            Batch.company_id == cid,
            Batch.product_id == pid,
            Batch.remaining > 0,
            Batch.date <= d,
        )
        .order_by(Batch.date, Batch.id)
        .with_for_update()
    ).all()
    available = sum(b.remaining for b in batches)
    if available < quantity and not allow_partial:
        fail("Недостаточно остатка товара у выбранной компании")
    result = []
    need = quantity
    for b in batches:
        if not need:
            break
        n = min(need, b.remaining)
        cost = (
            b.remaining_cost
            if n == b.remaining
            else rounded(b.remaining_cost * n, b.remaining)
        )
        b.remaining -= n
        b.remaining_cost -= cost
        need -= n
        result.append((b, n, cost))
    return result


def sale(db, user, p, confirmed_marketplace=False):
    get_company(db, user, p.company_id)
    scope_product(db, user, p.product_id, p.company_id)
    account = check_account(db, p.company_id, p.account_id)
    if p.customer_id:
        customer = db.get(Customer, p.customer_id)
        if not customer or customer.company_id != p.company_id:
            fail("Покупатель не принадлежит компании")
    if account.channel == "B2B" and not p.customer_id:
        fail("Для B2B укажите покупателя")
    if p.due_date and p.due_date < p.date:
        fail("Срок оплаты раньше продажи")
    lock_product(db, p.product_id)
    if not confirmed_marketplace:
        check_date(db, p.company_id, p.date)
    gross_revenue = p.quantity * p.unit_price
    if p.discount > gross_revenue:
        fail("Скидка не может быть больше стоимости продажи")
    revenue = gross_revenue - p.discount
    if p.paid > revenue:
        fail("Оплата больше выручки")
    marketplace_sale = confirmed_marketplace and account.channel in {"Wildberries", "Kaspi", "Ozon"}
    allocation = take_fifo(db, p.company_id, p.product_id, p.quantity, p.date,
                           allow_partial=marketplace_sale)
    allocated_quantity = sum(n for _b, n, _c in allocation)
    unallocated_quantity = p.quantity - allocated_quantity
    cogs_pending = unallocated_quantity > 0
    obj = Sale(
        **p.model_dump(exclude={"unit_price", "paid"}),
        revenue=revenue,
        cogs=sum(c for b, n, c in allocation),
        cogs_pending=cogs_pending,
    )
    db.add(obj)
    db.flush()
    for b, n, c in allocation:
        db.add(Allocation(sale_id=obj.id, batch_id=b.id, quantity=n, cost=c))
        db.add(
            Movement(
                company_id=p.company_id,
                product_id=p.product_id,
                batch_id=b.id,
                date=p.date,
                quantity=-n,
                cost=-c,
                kind="sale",
                reference=p.reference,
            )
        )
    if unallocated_quantity:
        # Revenue and sold units are confirmed facts. Record the missing FIFO
        # quantity as a visible stock deficit now; never silently leave stock
        # unchanged just because the corresponding opening lot is not entered.
        db.add(Movement(
            company_id=p.company_id, product_id=p.product_id, batch_id=None,
            date=p.date, quantity=-unallocated_quantity, cost=0,
            kind="sale_pending_fifo", reference=p.reference,
        ))
    cash_entry(
        db,
        company_id=p.company_id,
        sale_id=obj.id,
        reference="sale:" + p.reference,
        date=p.date,
        amount=p.paid,
        category="Продажа",
        description=account.channel,
    )
    audit(db, user, "post", "sales", obj.id)
    return obj



def settle_pending_sale_cogs(db, user, sale_obj):
    """Attach FIFO to an already-confirmed marketplace sale once historical stock exists."""
    if not getattr(sale_obj, "cogs_pending", False):
        return False
    get_company(db, user, sale_obj.company_id)
    sale_obj=db.scalar(select(Sale).where(Sale.id==sale_obj.id).with_for_update().execution_options(populate_existing=True))
    if not sale_obj.cogs_pending: return False
    lock_product(db, sale_obj.product_id)
    already_allocated = db.scalar(select(func.coalesce(func.sum(Allocation.quantity), 0)).where(
        Allocation.sale_id == sale_obj.id
    )) or 0
    remaining_quantity = max(0, sale_obj.quantity - int(already_allocated))
    if not remaining_quantity:
        sale_obj.cogs_pending = False
        return True
    try:
        allocation = take_fifo(db, sale_obj.company_id, sale_obj.product_id, remaining_quantity, sale_obj.date)
    except HTTPException as exc:
        if "Недостаточно остатка товара" in str(exc.detail):
            return False
        raise
    sale_obj.cogs = int(sale_obj.cogs or 0) + sum(c for b, n, c in allocation)
    sale_obj.cogs_pending = False
    for b, n, c in allocation:
        db.add(Allocation(sale_id=sale_obj.id, batch_id=b.id, quantity=n, cost=c))
        # Quantity was already posted when the marketplace sale was confirmed.
        # This cost-only adjustment closes FIFO without double-decrementing stock.
        db.add(Movement(company_id=sale_obj.company_id, product_id=sale_obj.product_id,
                        batch_id=b.id, date=sale_obj.date, quantity=0, cost=-c,
                        kind="sale_fifo_cost", reference=sale_obj.reference))
    db.flush()
    for ret in db.scalars(select(Return).where(Return.sale_id == sale_obj.id).order_by(Return.date,Return.id)):
        restore_return_cost(db, sale_obj, ret)
    audit(db,user,'reconcile_fifo','sales',sale_obj.id,{'cogs':sale_obj.cogs})
    return True


def restock_return_inventory(db, user, ret):
    """Add a inspected, saleable return to FIFO stock once."""
    ret = db.scalar(select(Return).where(Return.id == ret.id).with_for_update())
    if not ret:
        fail("Возврат не найден")
    if ret.inventory_status != "restocked":
        fail("Возврат не прошёл проверку пригодности")
    sale = db.get(Sale, ret.sale_id)
    if not sale:
        fail("Исходная продажа не найдена")
    lock_product(db, sale.product_id)
    links = db.scalars(
        select(ReturnInventoryAllocation)
        .where(ReturnInventoryAllocation.return_id == ret.id)
        .order_by(ReturnInventoryAllocation.id)
        .with_for_update()
    ).all()
    restored = 0
    for link in links:
        if link.restocked:
            continue
        batch = db.scalar(select(Batch).where(Batch.id == link.batch_id).with_for_update())
        if not batch or batch.product_id != sale.product_id or batch.company_id != ret.company_id:
            fail("FIFO-партия возврата не найдена")
        batch.remaining += link.quantity
        batch.remaining_cost += link.cost
        link.restocked = True
        db.add(Movement(
            company_id=ret.company_id, product_id=sale.product_id, batch_id=batch.id,
            date=business_today(), quantity=link.quantity, cost=link.cost,
            kind="return", reference=f"return-restock:{ret.id}:{link.id}",
        ))
        restored += link.quantity
    db.flush()
    return restored


def restore_return_cost(db, sale_obj, ret):
    """Attach the original FIFO batches to a return after a pending sale gets cost."""
    need = ret.quantity
    cost = 0
    allocations = db.scalars(
        select(Allocation).where(Allocation.sale_id == sale_obj.id)
        .order_by(Allocation.id).with_for_update()
    ).all()
    links = []
    for allocation in allocations:
        quantity = min(need, allocation.quantity - allocation.returned)
        if not quantity:
            continue
        amount = (
            allocation.cost - allocation.returned_cost
            if quantity == allocation.quantity - allocation.returned
            else rounded((allocation.cost - allocation.returned_cost) * quantity,
                         allocation.quantity - allocation.returned)
        )
        allocation.returned += quantity
        allocation.returned_cost += amount
        links.append(ReturnInventoryAllocation(
            return_id=ret.id, batch_id=allocation.batch_id,
            quantity=quantity, cost=amount, restocked=False,
        ))
        cost += amount
        need -= quantity
        if not need:
            break
    if need:
        fail("Не удалось связать возврат с исходными FIFO-партиями")
    ret.cogs = cost
    db.add_all(links)
    db.flush()
    if ret.inventory_status == "restocked":
        restock_return_inventory(db, None, ret)
    return cost


def reconcile_pending_cogs(db,user,company_id,product_ids=None):
    get_company(db,user,company_id)
    q=select(Sale).where(Sale.company_id==company_id,Sale.cogs_pending.is_(True))
    if product_ids: q=q.where(Sale.product_id.in_(product_ids))
    count=0
    for obj in db.scalars(q.order_by(Sale.date,Sale.id).with_for_update()):
        count+=int(settle_pending_sale_cogs(db,user,obj))
    return count


def opening_inventory(db,user,p):
    get_company(db,user,p.company_id)
    scope_product(db,user,p.product_id,p.company_id)
    lock_product(db,p.product_id)
    if p.currency=='KZT' and p.fx_rate!=10000: fail('Курс KZT должен быть равен 1')
    total=rounded(p.quantity*p.unit_cost*p.fx_rate,10000)
    batch=Batch(company_id=p.company_id,product_id=p.product_id,date=p.date,quantity=p.quantity,
        remaining=p.quantity,total_cost=total,remaining_cost=total)
    db.add(batch);db.flush()
    db.add(Movement(company_id=p.company_id,product_id=p.product_id,batch_id=batch.id,date=p.date,
        quantity=p.quantity,cost=total,kind='opening',reference=p.reference))
    db.flush()
    audit(db,user,'opening_inventory','batches',batch.id,p.model_dump(mode='json'))
    reconciled=reconcile_pending_cogs(db,user,p.company_id,[p.product_id])
    return {'batch_id':batch.id,'reconciled_cogs':reconciled}


def return_sale(db, user, p):
    sale = db.get(Sale, p.sale_id)
    if not sale:
        fail("Продажа не найдена")
    get_company(db, user, sale.company_id)
    lock_product(db, sale.product_id)
    sale = db.scalar(select(Sale).where(Sale.id == sale.id).with_for_update())
    check_date(db, sale.company_id, p.date)
    if p.date < sale.date:
        fail("Возврат раньше продажи")
    allocations = db.scalars(
        select(Allocation).where(Allocation.sale_id == sale.id)
        .order_by(Allocation.id).with_for_update()
    ).all()
    prior_return_units = db.scalar(
        select(func.coalesce(func.sum(Return.quantity), 0)).where(Return.sale_id == sale.id)
    )
    available = (sale.quantity - prior_return_units) if sale.cogs_pending else sum(
        allocation.quantity - allocation.returned for allocation in allocations
    )
    if p.quantity > available:
        fail("Возврат превышает проданное количество")
    returned_revenue = db.scalar(
        select(func.coalesce(func.sum(Return.revenue), 0)).where(Return.sale_id == sale.id)
    )
    previously_returned = prior_return_units if sale.cogs_pending else sum(
        allocation.returned for allocation in allocations
    )
    revenue = (
        sale.revenue - returned_revenue
        if p.quantity == sale.quantity - previously_returned
        else rounded(sale.revenue * p.quantity, sale.quantity)
    )
    if p.refund > revenue:
        fail("Выплата больше суммы возврата")
    net_paid = db.scalar(
        select(func.coalesce(func.sum(CashEntry.amount), 0)).where(CashEntry.sale_id == sale.id)
    )
    if p.refund > net_paid:
        fail("Нельзя вернуть больше полученной оплаты")

    need = p.quantity
    cost = 0
    links = []
    for allocation in allocations:
        quantity = min(need, allocation.quantity - allocation.returned)
        if not quantity:
            continue
        amount = (
            allocation.cost - allocation.returned_cost
            if quantity == allocation.quantity - allocation.returned
            else rounded(
                (allocation.cost - allocation.returned_cost) * quantity,
                allocation.quantity - allocation.returned,
            )
        )
        batch = db.scalar(select(Batch).where(Batch.id == allocation.batch_id).with_for_update())
        allocation.returned += quantity
        allocation.returned_cost += amount
        links.append((batch.id, quantity, amount))
        cost += amount
        need -= quantity
        if not need:
            break

    obj = Return(
        company_id=sale.company_id, sale_id=sale.id, date=p.date,
        reference=p.reference, quantity=p.quantity, revenue=revenue, cogs=cost,
        inventory_status="requested",
    )
    db.add(obj)
    db.flush()
    for batch_id, quantity, amount in links:
        db.add(ReturnInventoryAllocation(
            return_id=obj.id, batch_id=batch_id, quantity=quantity, cost=amount,
        ))
    cash_entry(
        db, company_id=sale.company_id, sale_id=sale.id,
        reference="return:" + p.reference, date=p.date, amount=-p.refund,
        category="Возврат", description=sale.reference,
    )
    audit(db, user, "post", "returns", obj.id)
    return obj


def expense(db, user, p):
    get_company(db, user, p.company_id)
    if p.account_id:
        check_account(db, p.company_id, p.account_id)
    if p.amount < 0 and (p.category not in {
        "Marketplace commission", "Marketplace commission VAT", "Marketplace acquiring",
        "Marketplace logistics", "Marketplace storage", "Marketplace acceptance",
        "Marketplace penalties", "Marketplace deductions",
    } or p.paid):
        fail("Отрицательная корректировка разрешена только для непогашенных расходов Marketplace")
    obj = Expense(**p.model_dump(exclude={"paid"}))
    db.add(obj)
    db.flush()
    if p.paid:
        cash_entry(
            db,
            company_id=p.company_id,
            expense_id=obj.id,
            reference="expense:" + p.reference,
            date=p.date,
            amount=-p.amount,
            category=p.category,
            description=p.description,
        )
    audit(db, user, "post", "expenses", obj.id)
    return obj


def payment(db, user, p):
    if p.amount == 0:
        fail("Сумма платежа не может быть нулевой")
    get_company(db, user, p.company_id)
    if sum(x is not None for x in (p.sale_id, p.purchase_id, p.expense_id)) > 1:
        fail("Платёж относится только к одному документу")
    for field, model in [
        ("sale_id", Sale),
        ("purchase_id", Purchase),
        ("expense_id", Expense),
    ]:
        if getattr(p, field):
            obj = db.scalar(
                select(model).where(model.id == getattr(p, field)).with_for_update()
            )
            if not obj or obj.company_id != p.company_id:
                fail("Документ оплаты не принадлежит компании")
            if p.date < obj.date:
                fail("Оплата раньше документа; аванс учитывайте отдельно")
            paid = db.scalar(
                select(func.coalesce(func.sum(CashEntry.amount), 0)).where(
                    getattr(CashEntry, field) == obj.id
                )
            )
            if model == Sale:
                returns = db.scalar(
                    select(func.coalesce(func.sum(Return.revenue), 0)).where(
                        Return.sale_id == obj.id
                    )
                )
                due = obj.revenue - returns
                if paid + p.amount > max(due, paid) or paid + p.amount < 0:
                    fail("Сумма оплаты превышает задолженность/полученные деньги")
                if p.amount < 0 and -p.amount > max(0, paid - due):
                    fail("Для возврата сначала проведите возврат товара")
            else:
                total = obj.total if model == Purchase else obj.amount
                if p.amount >= 0 or -paid - p.amount > total:
                    fail("Некорректная исходящая оплата")
    obj = CashEntry(**p.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "post", "cash", obj.id)
    return obj


def adjust(db, user, p):
    get_company(db, user, p.company_id)
    scope_product(db, user, p.product_id, p.company_id)
    lock_product(db, p.product_id)
    check_date(db, p.company_id, p.date)
    if p.quantity == 0:
        fail("Количество не может быть нулевым")
    if p.kind == "receipt" and p.quantity < 0:
        fail("Приход не может уменьшать остаток")
    if p.kind in ("writeoff", "defect") and p.quantity > 0:
        fail("Списание/брак должны уменьшать остаток")
    ref = p.reference or ("adjust:" + __import__("uuid").uuid4().hex)
    if p.quantity > 0:
        b = Batch(
            company_id=p.company_id,
            product_id=p.product_id,
            date=p.date,
            quantity=p.quantity,
            remaining=p.quantity,
            total_cost=p.quantity * p.unit_cost,
            remaining_cost=p.quantity * p.unit_cost,
        )
        db.add(b)
        db.flush()
        parts = [(b, p.quantity, p.quantity * p.unit_cost)]
    else:
        parts = [
            (b, -n, -c)
            for b, n, c in take_fifo(
                db, p.company_id, p.product_id, -p.quantity, p.date
            )
        ]
    movements = []
    for b, n, c in parts:
        movement = Movement(
                company_id=p.company_id,
                product_id=p.product_id,
                batch_id=b.id,
                date=p.date,
                quantity=n,
                cost=c,
                kind=p.kind,
                reference=p.reason,
            )
        db.add(movement)
        movements.append(movement)
    # Only economic losses hit P&L. A count correction changes inventory, but is not
    # silently classified as an operating loss; accountant can post a separate expense.
    if p.kind in ("writeoff", "defect") and p.quantity < 0 and sum(c for b, n, c in parts) < 0:
        db.add(
            Expense(
                company_id=p.company_id,
                reference=ref,
                date=p.date,
                category="Брак" if p.kind == "defect" else "Списание склада",
                description=p.reason,
                amount=-sum(c for b, n, c in parts),
            )
        )
    audit(db, user, "adjust", "inventory", details=p.model_dump(mode="json"))
    db.flush()
    if p.quantity > 0: reconcile_pending_cogs(db,user,p.company_id,[p.product_id])
    return {"reference": ref, "movement_ids": [m.id for m in movements]}


def marketplace_source_event_days(db, user, company_id=None, account_ids=None, active_only=True):
    """Return source-event dates needed to assess report completeness.

    The dashboard summary uses the same candidate rows for selected period,
    today, and month. Read them once and reuse the dates across those windows.
    """
    if account_ids is None:
        account_query = scope_query(select(Account), Account, user)
        if active_only:
            account_query = account_query.where(Account.active.is_(True))
        if company_id:
            account_query = account_query.where(Account.company_id == company_id)
        account_ids = {account.id for account in db.scalars(account_query)}
    else:
        account_ids = set(account_ids)
    if not account_ids:
        return []
    source_query = scope_query(
        select(MarketplaceRecord.reason_code, MarketplaceRecord.payload),
        MarketplaceRecord,
        user,
    ).where(
        MarketplaceRecord.account_id.in_(account_ids),
        MarketplaceRecord.status != "projected",
        MarketplaceRecord.stage_status != "ignored_non_financial",
    )
    if company_id:
        source_query = source_query.where(MarketplaceRecord.company_id == company_id)
    from .marketplace_pipeline import _day, Pending
    event_days = []
    for reason_code, raw_payload in db.execute(source_query).yield_per(1000):
        if reason_code == "DUPLICATE_EVENT":
            continue
        payload = raw_payload or {}
        record_type = payload.get("record_type")
        operation = str(payload.get("sellerOperName") or payload.get("supplier_oper_name") or payload.get("doc_type_name") or "").lower()
        confirmed = (
            record_type == "sale"
            or (record_type == "realization" and operation in {"продажа", "sale", "возврат", "return"})
            or (record_type == "posting" and payload.get("status") in {"delivered", "completed"})
            or (record_type == "order_entry" and payload.get("order_status") == "COMPLETED")
        )
        if not confirmed:
            continue
        try:
            day = _day(
                payload.get("saleDt") or payload.get("sale_dt") or payload.get("date")
                or payload.get("completed_date") or payload.get("delivered_at")
                or payload.get("shipment_date") or payload.get("created_at"),
                "Asia/Almaty" if record_type == "order_entry" else None,
            )
        except Pending:
            day = None
        event_days.append(day)
    return event_days


def report_headline(db, user, start, end, company_id=None, pending_source_days=None, include_balances=True):
    """Calculate the small dashboard KPI set from only the selected date window.

    The full report includes inventory, receivables, historical cash and product
    breakdowns. Headline cards need only period sales, returns, costs and expenses.
    """
    if end < start:
        fail("Конец периода раньше начала")
    if company_id:
        scope(user, company_id)
    account_query = scope_query(select(Account), Account, user).where(Account.active.is_(True))
    accounts = {a.id: a for a in db.scalars(account_query)}
    account_ids = set(accounts)
    if not account_ids:
        return {
            "revenue": 0, "cogs": 0, "gross_profit": 0, "net_profit": 0, "margin": None,
            "units": 0, "returns": 0, "return_units": 0, "commission": 0,
            "commission_actual": 0, "commission_estimated": 0, "commission_estimate_suppressed": False,
            "logistics": 0, "advertising": 0, "expenses": 0, "profit_complete": True,
            "net_profit_complete": True, "pending_cogs_sales": 0, "channel_summary": [],
        }

    sales_query = scope_query(select(Sale), Sale, user).where(
        Sale.account_id.in_(account_ids), Sale.date >= start, Sale.date <= end
    )
    if company_id:
        sales_query = sales_query.where(Sale.company_id == company_id)
    sales = list(db.scalars(sales_query))

    returns_query = scope_query(select(Return).join(Sale, Return.sale_id == Sale.id), Return, user).where(
        Sale.account_id.in_(account_ids), Return.date >= start, Return.date <= end
    )
    if company_id:
        returns_query = returns_query.where(Return.company_id == company_id)
    returns = list(db.scalars(returns_query))
    expenses_query = scope_query(select(Expense), Expense, user).where(
        Expense.date >= start, Expense.date <= end
    )
    if company_id:
        expenses_query = expenses_query.where(Expense.company_id == company_id)
    expenses = [
        expense for expense in db.scalars(expenses_query)
        if expense.account_id is None or expense.account_id in account_ids
    ]

    from .marketplace_costs import resolve_cost_overrides
    sale_cogs, return_cogs, pending_cost_ids = resolve_cost_overrides(db, sales, returns, accounts)
    revenue = sum(sale.revenue for sale in sales) - sum(ret.revenue for ret in returns)
    restocked_returns = [ret for ret in returns if ret.inventory_status == "restocked"]
    cogs = sum(sale_cogs.get(sale.id, sale.cogs) for sale in sales) - sum(
        return_cogs.get(ret.id, ret.cogs) for ret in restocked_returns
    )

    commission_actual = sum(sale.commission for sale in sales) + sum(
        expense.amount for expense in expenses
        if expense.category in {"Marketplace commission", "Marketplace commission VAT"}
    )
    estimates, _rate, _suppressed = kaspi_commission_estimates(
        db, user, start, end, company_id, None, sales, expenses, accounts
    )
    commission = commission_actual + sum(estimates.values())
    logistics = sum(sale.logistics for sale in sales) + sum(
        expense.amount for expense in expenses if expense.category == "Marketplace logistics"
    )
    advertising = sum(sale.advertising for sale in sales) + sum(
        expense.amount for expense in expenses if expense.category == "Реклама"
    )
    operating = sum(
        expense.amount for expense in expenses
        if expense.category not in {"Реклама", "Marketplace commission", "Marketplace commission VAT", "Marketplace logistics"}
    )

    if pending_source_days is None:
        pending_source_days = marketplace_source_event_days(db, user, company_id)
    pending_source = any(
        day is None or start <= day <= end
        for day in pending_source_days
    )

    profit_complete = not pending_cost_ids and not pending_source
    net_profit_complete = profit_complete and not any(
        ret.inventory_status in {"requested", "approved", "in_transit", "received", "inspection"}
        for ret in returns
    )
    gross_profit = revenue - cogs if profit_complete else None
    net_profit = gross_profit - commission - logistics - advertising - operating if net_profit_complete else None
    units = sum(sale.quantity for sale in sales) - sum(ret.quantity for ret in returns)
    channel_totals = defaultdict(lambda: {"revenue": 0, "quantity": 0, "returns": 0})
    for sale in sales:
        channel = accounts[sale.account_id].channel
        channel_totals[channel]["revenue"] += sale.revenue
        channel_totals[channel]["quantity"] += sale.quantity
    account_totals = defaultdict(lambda: {"revenue": 0, "quantity": 0, "returns": 0})
    for sale in sales:
        name = accounts[sale.account_id].name
        account_totals[name]["revenue"] += sale.revenue
        account_totals[name]["quantity"] += sale.quantity
    sales_by_id = {sale.id: sale for sale in sales}
    for ret in returns:
        sale = sales_by_id.get(ret.sale_id)
        if sale:
            channel = accounts[sale.account_id].channel
            channel_totals[channel]["revenue"] -= ret.revenue
            channel_totals[channel]["quantity"] -= ret.quantity
            channel_totals[channel]["returns"] += ret.revenue
            name = accounts[sale.account_id].name
            account_totals[name]["revenue"] -= ret.revenue
            account_totals[name]["quantity"] -= ret.quantity
            account_totals[name]["returns"] += ret.revenue

    if include_balances:
        # Keep the all-time cards in SQL. Materializing every historical sale,
        # return and cash row for each dashboard period made this endpoint slow.
        all_sales_query = scope_query(select(Sale.id, Sale.account_id, Sale.revenue), Sale, user).where(
            Sale.account_id.in_(account_ids), Sale.date <= end
        )
        if company_id:
            all_sales_query = all_sales_query.where(Sale.company_id == company_id)
        all_sales = all_sales_query.subquery()
    
        all_returns_query = scope_query(
            select(Return.sale_id, func.sum(Return.revenue).label("revenue"))
            .join(Sale, Return.sale_id == Sale.id), Return, user
        ).where(
            Sale.account_id.in_(account_ids), Sale.date <= end, Return.date <= end
        )
        if company_id:
            all_returns_query = all_returns_query.where(
                Return.company_id == company_id, Sale.company_id == company_id
            )
        all_returns = all_returns_query.group_by(Return.sale_id).subquery()
    
        cash_totals_query = scope_query(
            select(
                func.coalesce(func.sum(CashEntry.amount), 0),
                func.coalesce(func.sum(case((CashEntry.date < start, CashEntry.amount), else_=0)), 0),
                func.coalesce(func.sum(case((CashEntry.date >= start, case((CashEntry.amount > 0, CashEntry.amount), else_=0)), else_=0)), 0),
                func.coalesce(func.sum(case((CashEntry.date >= start, case((CashEntry.amount < 0, -CashEntry.amount), else_=0)), else_=0)), 0),
                func.coalesce(func.sum(case((CashEntry.date >= start, CashEntry.amount), else_=0)), 0),
            ), CashEntry, user
        ).where(CashEntry.date <= end)
        if company_id:
            cash_totals_query = cash_totals_query.where(CashEntry.company_id == company_id)
        cash_totals = db.execute(cash_totals_query).one()
        cash, cash_opening, cash_inflow, cash_outflow, cash_flow = map(int, cash_totals)
    
        paid_query = scope_query(
            select(CashEntry.sale_id, func.sum(CashEntry.amount).label("paid")), CashEntry, user
        ).where(CashEntry.date <= end, CashEntry.sale_id.is_not(None))
        if company_id:
            paid_query = paid_query.where(CashEntry.company_id == company_id)
        paid_by_sale = paid_query.group_by(CashEntry.sale_id).subquery()
    
        net = all_sales.c.revenue - func.coalesce(all_returns.c.revenue, 0)
        paid = func.coalesce(paid_by_sale.c.paid, 0)
        receivable_query = (
            select(
                func.coalesce(func.sum(case(
                    (Account.channel == "B2B", case((net > paid, net - paid), else_=0)), else_=0
                )), 0),
                func.coalesce(func.sum(case((paid > net, paid - net), else_=0)), 0),
            )
            .select_from(all_sales)
            .join(Account, Account.id == all_sales.c.account_id)
            .outerjoin(all_returns, all_returns.c.sale_id == all_sales.c.id)
            .outerjoin(paid_by_sale, paid_by_sale.c.sale_id == all_sales.c.id)
        )
        if company_id:
            receivable_query = receivable_query.where(Account.company_id == company_id)
        b2b_debt, refunds_payable = map(int, db.execute(receivable_query).one())
    
        movement_query = scope_query(select(func.coalesce(func.sum(Movement.cost), 0)), Movement, user).where(Movement.date <= end)
        if company_id:
            movement_query = movement_query.where(Movement.company_id == company_id)
        stock_value = int(db.scalar(movement_query) or 0)
    
    
    else:
        cash = cash_flow = cash_opening = cash_inflow = cash_outflow = 0
        b2b_debt = refunds_payable = stock_value = 0

    return {
        "revenue": revenue,
        "cogs": cogs if profit_complete else None,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
        "margin": round(net_profit / revenue * 100, 2) if net_profit is not None and revenue else None,
        "units": units,
        "returns": sum(ret.revenue for ret in returns),
        "return_units": sum(ret.quantity for ret in returns),
        "commission": commission,
        "commission_actual": commission_actual,
        "commission_estimated": sum(estimates.values()),
        "commission_estimate_suppressed": _suppressed,
        "logistics": logistics,
        "advertising": advertising,
        "expenses": operating,
        "profit_complete": profit_complete,
        "net_profit_complete": net_profit_complete,
        "pending_cogs_sales": len(pending_cost_ids),
        "channel_summary": [{"channel": name, **values} for name, values in channel_totals.items()],
        "channels": [{"name": name, "revenue": values["revenue"], "quantity": values["quantity"], "returns": values["returns"]} for name, values in account_totals.items()],
        "stock_value": stock_value,
        "cash": cash,
        "cash_flow": cash_flow,
        "cash_opening": cash_opening,
        "cash_inflow": cash_inflow,
        "cash_outflow": cash_outflow,
        "cash_closing": cash_opening + cash_inflow - cash_outflow,
        "b2b_debt": b2b_debt,
        "refunds_payable": refunds_payable,
    }


def report(db, user, start, end, company_id=None, account_id=None, active_only=False):
    if end < start:
        fail("Конец периода раньше начала")
    if company_id:
        scope(user, company_id)
    if account_id:
        a = db.get(Account, account_id)
        if not a:
            fail("Аккаунт не найден")
        scope(user, a.company_id)

    def rows(model, period=True):
        q = scope_query(select(model), model, user)
        if company_id:
            q = q.where(model.company_id == company_id)
        if hasattr(model, "date"):
            q = q.where(model.date <= end)
            if period:
                q = q.where(model.date >= start)
        return list(db.scalars(q))

    # Historical reports retain disconnected stores. The business overview can
    # opt into active-only scope, while explicit account reports remain auditable.
    account_query = scope_query(select(Account), Account, user)
    if account_id:
        account_query = account_query.where(Account.id == account_id)
    elif active_only:
        account_query = account_query.where(Account.active.is_(True))
    accounts = {a.id: a for a in db.scalars(account_query)}
    account_ids = set(accounts)
    sales = [s for s in rows(Sale) if s.account_id in account_ids]
    # The detailed report still needs historical sales for debt and refund balances;
    # keep the set scoped to the stores selected for this report.
    allsales = {s.id: s for s in rows(Sale, False) if s.account_id in account_ids}
    returns_query = scope_query(
        select(Return).join(Sale, Return.sale_id == Sale.id), Return, user
    ).where(
        Sale.account_id.in_(account_ids), Sale.date <= end,
        Return.date >= start, Return.date <= end,
    )
    if company_id:
        returns_query = returns_query.where(
            Return.company_id == company_id, Sale.company_id == company_id
        )
    returns = list(db.scalars(returns_query))
    pending_return_inspection_units = sum(
        r.quantity for r in returns
        if r.inventory_status in {"requested", "approved", "in_transit", "received", "inspection"}
    )
    expenses = [e for e in rows(Expense) if e.account_id is None or e.account_id in account_ids]
    if account_id:
        sales = [s for s in sales if s.account_id == account_id]
        returns = [r for r in returns if allsales[r.sale_id].account_id == account_id]
        expenses = [e for e in expenses if e.account_id == account_id]
    from .marketplace_costs import resolve_cost_overrides
    sale_cogs, return_cogs, pending_cost_ids = resolve_cost_overrides(db, sales, returns, accounts)
    rev = sum(s.revenue for s in sales) - sum(r.revenue for r in returns)
    pending_cogs_sales = [s for s in sales if s.id in pending_cost_ids]
    pending_return_sales = {r.sale_id for r in returns if r.sale_id in pending_cost_ids}
    pending_sources = [
        day for day in marketplace_source_event_days(
            db, user, company_id, account_ids=account_ids, active_only=active_only
        )
        if day is None or start <= day <= end
    ]
    profit_complete = not pending_cogs_sales and not pending_return_sales and not pending_sources
    net_profit_complete = profit_complete and pending_return_inspection_units == 0
    restocked_returns = [r for r in returns if r.inventory_status == "restocked"]
    cogs = sum(sale_cogs.get(s.id, s.cogs) for s in sales) - sum(return_cogs.get(r.id, r.cogs) for r in restocked_returns)
    commission_categories = {"Marketplace commission", "Marketplace commission VAT"}
    commission_actual = sum(s.commission for s in sales) + sum(
        e.amount for e in expenses if e.category in commission_categories
    )
    kaspi_estimates, commission_rate, commission_estimate_suppressed = kaspi_commission_estimates(
        db, user, start, end, company_id, account_id, sales, expenses, accounts
    )
    commission_estimated = sum(kaspi_estimates.values())
    commissions = commission_actual + commission_estimated
    logistics = sum(s.logistics for s in sales) + sum(
        e.amount for e in expenses if e.category == "Marketplace logistics"
    )
    ads = sum(s.advertising for s in sales) + sum(
        e.amount for e in expenses if e.category == "Реклама"
    )
    operating = sum(
        e.amount for e in expenses
        if e.category not in {"Реклама", "Marketplace commission", "Marketplace commission VAT", "Marketplace logistics"}
    )
    known_gp = rev - cogs
    known_np = known_gp - commissions - logistics - ads - operating
    # Revenue/units remain authoritative. Profit requires FIFO or a dated marketplace cost.
    gp = known_gp if profit_complete else None
    np = known_np if net_profit_complete else None
    cash = rows(CashEntry, False)
    cash_period = [c for c in cash if start <= c.date <= end]
    cash_opening = sum(c.amount for c in cash if c.date < start)
    cash_inflow = sum(c.amount for c in cash_period if c.amount > 0)
    cash_outflow = -sum(c.amount for c in cash_period if c.amount < 0)
    cash_by_category = defaultdict(lambda: {"inflow": 0, "outflow": 0, "net": 0})
    cash_daily = defaultdict(lambda: {"inflow": 0, "outflow": 0, "net": 0})
    for c in cash_period:
        bucket = cash_by_category[c.category or "Прочее"]
        day = cash_daily[str(c.date)]
        if c.amount >= 0:
            bucket["inflow"] += c.amount
            day["inflow"] += c.amount
        else:
            bucket["outflow"] += -c.amount
            day["outflow"] += -c.amount
        bucket["net"] += c.amount
        day["net"] += c.amount
    movements = rows(Movement, False)
    returns_all = rows(Return, False)
    return_by_sale = defaultdict(int)
    paid_by_sale = defaultdict(int)
    for ret in returns_all:
        return_by_sale[ret.sale_id] += ret.revenue
    for entry in cash:
        if entry.sale_id:
            paid_by_sale[entry.sale_id] += entry.amount
    debt = 0
    debt_rows = []
    for s in allsales.values():
        if s.account_id not in accounts:
            continue
        if account_id and s.account_id != account_id:
            continue
        net = s.revenue - return_by_sale[s.id]
        paid = paid_by_sale[s.id]
        due = max(0, net - paid)
        if due:
            debt_rows.append(
                {
                    "sale_id": s.id,
                    "reference": s.reference,
                    "customer_id": s.customer_id,
                    "channel": accounts[s.account_id].channel,
                    "due": due,
                    "due_date": s.due_date,
                    "overdue": bool(s.due_date and s.due_date < end),
                }
            )
        if accounts[s.account_id].channel == "B2B":
            debt += due
    channels = defaultdict(lambda: {"revenue": 0, "cogs": 0, "costs": 0, "quantity": 0, "pending_cogs": 0})
    channel_totals = defaultdict(lambda: {"revenue": 0, "cogs": 0, "costs": 0, "quantity": 0, "commission": 0, "logistics": 0, "advertising": 0, "returns": 0, "return_units": 0, "pending_cogs": 0})
    products = defaultdict(lambda: {"revenue": 0, "cogs": 0, "costs": 0, "quantity": 0, "pending_cogs": 0})
    products_by_channel = defaultdict(lambda: defaultdict(lambda: {"revenue": 0, "quantity": 0}))
    products_by_store = defaultdict(lambda: defaultdict(lambda: {"revenue": 0, "quantity": 0}))
    categories = defaultdict(lambda: {"revenue": 0, "cogs": 0, "costs": 0, "quantity": 0, "pending_cogs": 0})
    daily = defaultdict(lambda: {"revenue": 0, "profit": 0, "units": 0})
    catalog = {p.id: p for p in db.scalars(select(Product))}
    for s in sales:
        key = accounts[s.account_id].name
        channel = accounts[s.account_id].channel
        direct_costs = s.commission + s.logistics + s.advertising
        ch = channels[key]
        ch["revenue"] += s.revenue
        ch["cogs"] += sale_cogs.get(s.id, s.cogs)
        ch["costs"] += direct_costs
        ch["quantity"] += s.quantity
        ch["pending_cogs"] += int(s.id in pending_cost_ids)
        ct = channel_totals[channel]
        ct["revenue"] += s.revenue
        ct["cogs"] += sale_cogs.get(s.id, s.cogs)
        ct["costs"] += direct_costs
        ct["commission"] += s.commission
        ct["logistics"] += s.logistics
        ct["advertising"] += s.advertising
        ct["quantity"] += s.quantity
        ct["pending_cogs"] += int(s.id in pending_cost_ids)
        pr = products[s.product_id]
        pr["revenue"] += s.revenue
        pr["cogs"] += sale_cogs.get(s.id, s.cogs)
        pr["costs"] += direct_costs
        pr["quantity"] += s.quantity
        pr["pending_cogs"] += int(s.id in pending_cost_ids)
        for product_totals in (products_by_channel[channel], products_by_store[s.account_id]):
            product_totals[s.product_id]["revenue"] += s.revenue
            product_totals[s.product_id]["quantity"] += s.quantity
        cat = categories[catalog[s.product_id].category or "Без категории"]
        cat["revenue"] += s.revenue
        cat["cogs"] += sale_cogs.get(s.id, s.cogs)
        cat["costs"] += direct_costs
        cat["quantity"] += s.quantity
        cat["pending_cogs"] += int(s.id in pending_cost_ids)
        daily[str(s.date)]["revenue"] += s.revenue
        daily[str(s.date)]["units"] += s.quantity
        daily[str(s.date)]["profit"] += (
            s.revenue - sale_cogs.get(s.id, s.cogs) - s.commission - s.logistics - s.advertising
        )
    for r in returns:
        s = allsales[r.sale_id]
        if s.id in pending_cost_ids and s not in pending_cogs_sales:
            channels[accounts[s.account_id].name]['pending_cogs']+=1
            channel_totals[accounts[s.account_id].channel]['pending_cogs']+=1
            products[s.product_id]['pending_cogs']+=1
            categories[catalog[s.product_id].category or 'Без категории']['pending_cogs']+=1
        ch = channels[accounts[s.account_id].name]
        ch["revenue"] -= r.revenue
        return_cost = return_cogs.get(r.id, r.cogs) if r.inventory_status == "restocked" else 0
        ch["cogs"] -= return_cost
        ch["quantity"] -= r.quantity
        ct = channel_totals[accounts[s.account_id].channel]
        ct["revenue"] -= r.revenue
        ct["cogs"] -= return_cost
        ct["quantity"] -= r.quantity
        ct["returns"] += r.revenue
        ct["return_units"] += r.quantity
        pr = products[s.product_id]
        pr["revenue"] -= r.revenue
        pr["cogs"] -= return_cost
        pr["quantity"] -= r.quantity
        channel = accounts[s.account_id].channel
        for product_totals in (products_by_channel[channel], products_by_store[s.account_id]):
            product_totals[s.product_id]["revenue"] -= r.revenue
            product_totals[s.product_id]["quantity"] -= r.quantity
        cat = categories[catalog[s.product_id].category or "Без категории"]
        cat["revenue"] -= r.revenue
        cat["cogs"] -= return_cost
        cat["quantity"] -= r.quantity
        daily[str(r.date)]["revenue"] -= r.revenue
        daily[str(r.date)]["units"] -= r.quantity
        daily[str(r.date)]["profit"] -= r.revenue - return_cost
    for e in expenses:
        daily[str(e.date)]["profit"] -= e.amount
        if e.account_id:
            channels[accounts[e.account_id].name]["costs"] += e.amount
            ct = channel_totals[accounts[e.account_id].channel]
            ct["costs"] += e.amount
            if e.category in {"Marketplace commission", "Marketplace commission VAT"}: ct["commission"] += e.amount
            elif e.category == "Marketplace logistics": ct["logistics"] += e.amount
            elif e.category == "Реклама": ct["advertising"] += e.amount
    for (account_day, amount) in kaspi_estimates.items():
        aid, day = account_day
        account = accounts.get(aid)
        if account:
            channels[account.name]["costs"] += amount
            channel_totals["Kaspi"]["costs"] += amount
            channel_totals["Kaspi"]["commission"] += amount
            daily[str(day)]["profit"] -= amount
    # pending_sources contains event dates (not MarketplaceRecord rows).
    # Their effect is already represented by profit_complete and pending_source_events;
    # account/channel attribution is unavailable at this stage.
    def ranked_product_rows(totals, limit=50):
        return [
            {"id": pid, "sku": catalog[pid].sku, "name": catalog[pid].name, **values}
            for pid, values in sorted(
                totals.items(), key=lambda item: (item[1]["quantity"], item[1]["revenue"]), reverse=True
            ) if values["quantity"] > 0
        ][:limit]

    product_ranking_by_channel = {
        channel: ranked_product_rows(totals)
        for channel, totals in products_by_channel.items()
    }
    product_ranking_by_store = {
        str(account_id): {
            "store": accounts[account_id].name,
            "channel": accounts[account_id].channel,
            "products": ranked_product_rows(totals, limit=20),
        }
        for account_id, totals in products_by_store.items()
    }
    stock = defaultdict(lambda: {"quantity": 0, "value": 0})
    for m in movements:
        stock[m.product_id]["quantity"] += m.quantity
        stock[m.product_id]["value"] += m.cost
    period_days = max(1, (end - start).days + 1)
    stockrows = [
        {
            "product_id": pid,
            "sku": catalog[pid].sku,
            "name": catalog[pid].name,
            **stock[pid],
            "min_stock": catalog[pid].min_stock,
            "sold": products[pid]["quantity"],
            "unit_cost": rounded(stock[pid]["value"], stock[pid]["quantity"])
            if stock[pid]["quantity"] > 0
            else 0,
            "days_of_stock": round(
                stock[pid]["quantity"] / (products[pid]["quantity"] / period_days), 1
            )
            if products[pid]["quantity"] > 0
            else None,
            "turnover_days": round(
                period_days * stock[pid]["quantity"] / products[pid]["quantity"], 1
            )
            if products[pid]["quantity"] > 0
            else None,
            "velocity_per_day": round(products[pid]["quantity"] / period_days, 3),
        }
        for pid in catalog
    ]
    return {
        "start": str(start),
        "end": str(end),
        "currency": "KZT",
        "money_unit": "tiyn",
        "revenue": rev,
        "cogs": cogs if profit_complete else None,
        "known_cogs": cogs,
        "incomplete_reason": None if profit_complete else ("SOURCE_EVENTS_PENDING" if pending_sources else "COGS_PENDING"),
        "pending_source_events":len(pending_sources),
        "gross_profit": gp,
        "net_profit": np,
        "profit_complete": profit_complete,
        "net_profit_complete": net_profit_complete,
        "financial_complete": net_profit_complete,
        "pending_return_inspection_units": pending_return_inspection_units,
        "pending_cogs_sales": len({s.id for s in pending_cogs_sales} | pending_return_sales),
        "known_net_before_pending_cogs": known_np,
        "commission": commissions,
        "commission_actual": commission_actual,
        "commission_estimated": commission_estimated,
        "commission_estimate_suppressed": commission_estimate_suppressed,
        "commission_rate": commission_rate if commission_estimated else None,
        "logistics": logistics,
        "advertising": ads,
        "expenses": operating,
        "margin": round(np / rev * 100, 2) if (rev and np is not None) else None,
        "roi": round(np / (cogs + commissions + logistics + ads + operating) * 100, 2)
        if (np is not None and cogs + commissions + logistics + ads + operating)
        else None,
        "units": sum(s.quantity for s in sales) - sum(r.quantity for r in returns),
        "returns": sum(r.revenue for r in returns),
        "return_units": sum(r.quantity for r in returns),
        "cash": sum(c.amount for c in cash),
        "cash_flow": sum(c.amount for c in cash_period),
        "cash_opening": cash_opening,
        "cash_inflow": cash_inflow,
        "cash_outflow": cash_outflow,
        "cash_closing": cash_opening + cash_inflow - cash_outflow,
        "cash_by_category": [
            {"category": k, **v} for k, v in sorted(cash_by_category.items())
        ],
        "cash_daily": [
            {"date": k, **v} for k, v in sorted(cash_daily.items())
        ],
        "stock_value": sum(m.cost for m in movements),
        "b2b_debt": debt,
        "receivables": debt_rows,
        "refunds_payable": sum(
            max(0, paid_by_sale[s.id] - (s.revenue - return_by_sale[s.id]))
            for s in allsales.values()
        ),
        "channels": [
            {"name": k, **v, "cogs": None if v["pending_cogs"] else v["cogs"], "profit": None if v["pending_cogs"] else v["revenue"] - v["cogs"] - v["costs"]}
            for k, v in channels.items()
        ],
        "channel_summary": [
            {"channel": k, **v, "cogs": None if v["pending_cogs"] else v["cogs"], "profit": None if v["pending_cogs"] else v["revenue"] - v["cogs"] - v["costs"]}
            for k, v in channel_totals.items()
        ],
        "categories": [
            {"category": k, **v, "cogs": None if v["pending_cogs"] else v["cogs"], "gross_profit": None if v["pending_cogs"] else v["revenue"] - v["cogs"], "contribution_profit": None if v["pending_cogs"] else v["revenue"] - v["cogs"] - v["costs"]}
            for k, v in categories.items()
        ],
        "b2b": {
            "revenue": channel_totals["B2B"]["revenue"],
            "gross_profit": None if channel_totals["B2B"]["pending_cogs"] else channel_totals["B2B"]["revenue"] - channel_totals["B2B"]["cogs"],
            "net_profit": None if channel_totals["B2B"]["pending_cogs"] else channel_totals["B2B"]["revenue"] - channel_totals["B2B"]["cogs"] - channel_totals["B2B"]["costs"],
            "orders": sum(1 for s in sales if accounts[s.account_id].channel == "B2B"),
            "average_check": round(channel_totals["B2B"]["revenue"] / sum(1 for s in sales if accounts[s.account_id].channel == "B2B")) if any(accounts[s.account_id].channel == "B2B" for s in sales) else 0,
            "receivables": debt,
        },
        "products": [
            {
                "id": pid,
                "name": catalog[pid].name,
                **v,
                "cogs": None if v["pending_cogs"] else v["cogs"],
                "gross_profit": None if v["pending_cogs"] else v["revenue"] - v["cogs"],
                "contribution_profit": None if v["pending_cogs"] else v["revenue"] - v["cogs"] - v["costs"],
            }
            for pid, v in products.items()
        ],
        "products_by_channel": product_ranking_by_channel,
        "products_by_store": product_ranking_by_store,
        "daily": [{"date": k, **v, "profit": v["profit"] if net_profit_complete else None} for k, v in sorted(daily.items())],
        "stock": stockrows,
        "stock_alerts": [s for s in stockrows if s["quantity"] <= s["min_stock"]],
        "slow_products": [s for s in stockrows if s["quantity"] > 0 and s["sold"] <= 0],
        "scope_note": "Деньги и склад — по компаниям; прибыль — по выбранному аккаунту. Общие расходы без аккаунта не распределены."
        if account_id
        else "Консолидировано по доступным компаниям",
        "method": "FIFO; расходы по начислению; деньги по датам платежей; без автоматического расчёта налогов",
    }


def report_details(db, user, start, end, metric, company_id=None, account_id=None, active_only=False):
    """Explain a reported amount with deterministic source rows.

    This is deliberately not an AI function: every number comes from posted ERP
    records or from an explicit arithmetic bridge between report subtotals.
    """
    valid = {"revenue", "cogs", "gross_profit", "commission", "logistics", "advertising", "expenses", "net_profit", "cash", "cash_flow", "stock_value", "b2b_debt", "refunds_payable"}
    if metric not in valid:
        fail("Неизвестный показатель отчёта")
    summary = report(db, user, start, end, company_id, account_id, active_only)
    if summary[metric] is None:
        return {'metric':metric,'start':str(start),'end':str(end),'expected':None,'explained':None,
                'difference':None,'rows':[],'reason_code':'COGS_PENDING'}

    def scoped(model, period=True):
        q = scope_query(select(model), model, user)
        if company_id:
            q = q.where(model.company_id == company_id)
        if hasattr(model, "date"):
            q = q.where(model.date <= end)
            if period:
                q = q.where(model.date >= start)
        return list(db.scalars(q))

    account_query = scope_query(select(Account), Account, user)
    if account_id:
        account_query = account_query.where(Account.id == account_id)
    elif active_only:
        account_query = account_query.where(Account.active.is_(True))
    accounts = {a.id: a for a in db.scalars(account_query)}
    account_ids = set(accounts)
    sales = [sale for sale in scoped(Sale) if sale.account_id in account_ids]
    all_sales = {sale.id: sale for sale in scoped(Sale, False) if sale.account_id in account_ids}
    returns = [ret for ret in scoped(Return) if ret.sale_id in all_sales]
    expenses = [expense for expense in scoped(Expense) if expense.account_id is None or expense.account_id in account_ids]

    product_cache = {}

    def item(d, typ, ref, desc, amount, source_id=None, product_id=None, account_id=None):
        product = None
        if product_id is not None:
            if product_id not in product_cache:
                product_cache[product_id] = db.get(Product, product_id)
            product = product_cache[product_id]
        account = accounts.get(account_id) if account_id is not None else None
        return {"date": str(d) if d else None, "type": typ, "reference": ref or "—", "description": desc or "", "amount": amount, "source_id": source_id,
                "product_id": product_id, "product_name": product.name if product else "", "article": product.article if product else "",
                "sku": product.sku if product else "", "account_name": account.name if account else ""}

    rows = []
    if metric == "revenue":
        rows += [item(s.date, "Продажа", s.reference, accounts.get(s.account_id).name if accounts.get(s.account_id) else "", s.revenue, s.id, s.product_id, s.account_id) for s in sales]
        rows += [item(r.date, "Возврат", r.reference, "Уменьшение выручки", -r.revenue, r.id, all_sales[r.sale_id].product_id, all_sales[r.sale_id].account_id) for r in returns]
    elif metric == "cogs":
        rows += [item(s.date, "Продажа", s.reference, "Себестоимость проданного", -s.cogs, s.id, s.product_id, s.account_id) for s in sales]
        rows += [item(r.date, "Возврат", r.reference, "Восстановление себестоимости", r.cogs, r.id, all_sales[r.sale_id].product_id, all_sales[r.sale_id].account_id) for r in returns if r.inventory_status == "restocked"]
    elif metric in {"commission", "logistics"}:
        attr = metric
        title = "Комиссия" if metric == "commission" else "Логистика"
        rows = [item(s.date, title, s.reference, accounts.get(s.account_id).name if accounts.get(s.account_id) else "", -getattr(s, attr), s.id, s.product_id, s.account_id) for s in sales if getattr(s, attr)]
        categories = {"Marketplace commission", "Marketplace commission VAT"} if metric == "commission" else {"Marketplace logistics"}
        rows += [item(e.date, "Корректировка расхода" if e.amount < 0 else "Расход", e.reference,
                      e.description or e.category, -e.amount, e.id, account_id=e.account_id) for e in expenses if e.category in categories]
        if metric == "commission":
            estimates, rate, _suppressed = kaspi_commission_estimates(
                db, user, start, end, company_id, account_id, sales, expenses, accounts
            )
            rows += [
                item(day, "Расчётная комиссия Kaspi", accounts[aid].name,
                     f"Оценка {Decimal(rate) * 100}% по выданным заказам API; не банковское списание",
                     -amount, None)
                for (aid, day), amount in estimates.items()
            ]
    elif metric == "advertising":
        rows += [item(s.date, "Реклама продажи", s.reference, accounts.get(s.account_id).name if accounts.get(s.account_id) else "", -s.advertising, s.id, s.product_id, s.account_id) for s in sales if s.advertising]
        rows += [item(e.date, "Расход", e.reference, e.description or e.category, -e.amount, e.id) for e in expenses if e.category == "Реклама"]
    elif metric == "expenses":
        rows = [item(e.date, "Корректировка расхода" if e.amount < 0 else "Расход", e.reference, e.description or e.category, -e.amount, e.id) for e in expenses if e.category not in {"Реклама","Marketplace commission","Marketplace commission VAT","Marketplace logistics"}]
    elif metric in {"gross_profit", "net_profit"}:
        bridge = [("Выручка", summary["revenue"]), ("Себестоимость", -summary["cogs"])]
        if metric == "net_profit":
            bridge += [("Комиссии", -summary["commission"]), ("Логистика", -summary["logistics"]), ("Реклама", -summary["advertising"]), ("Операционные расходы", -summary["expenses"])]
        rows = [item(None, "Формула", "—", name, amount) for name, amount in bridge]
    elif metric in {"cash", "cash_flow"}:
        cash_rows = scoped(CashEntry, metric == "cash_flow")
        rows = [item(c.date, c.category or "Деньги", c.reference, c.description, c.amount, c.id, all_sales[c.sale_id].product_id if c.sale_id in all_sales else None, all_sales[c.sale_id].account_id if c.sale_id in all_sales else None) for c in cash_rows]
    elif metric == "stock_value":
        movements = scoped(Movement, False)
        catalog = {p.id: p for p in db.scalars(select(Product))}
        by_product = defaultdict(int)
        for m in movements:
            by_product[m.product_id] += m.cost
        rows = [item(end, "Остаток", catalog[pid].sku if pid in catalog else str(pid), catalog[pid].name if pid in catalog else "", value, pid, pid) for pid, value in by_product.items() if value]
    elif metric in {"b2b_debt", "refunds_payable"}:
        # report() already applies returns and payments as of the report date.
        if metric == "b2b_debt":
            rows = [item(x.get("due_date"), "Дебиторка", x["reference"], x["channel"], x["due"], x["sale_id"], all_sales[x["sale_id"]].product_id if x["sale_id"] in all_sales else None, all_sales[x["sale_id"]].account_id if x["sale_id"] in all_sales else None) for x in summary["receivables"] if x["channel"] == "B2B"]
        else:
            returns_all = scoped(Return, False)
            cash_all = scoped(CashEntry, False)
            returned = defaultdict(int); paid = defaultdict(int)
            for r in returns_all: returned[r.sale_id] += r.revenue
            for c in cash_all:
                if c.sale_id: paid[c.sale_id] += c.amount
            for s in all_sales.values():
                if account_id and s.account_id != account_id: continue
                amount = max(0, paid[s.id] - (s.revenue - returned[s.id]))
                if amount: rows.append(item(end, "К возврату", s.reference, "Получено больше чистой суммы продажи", amount, s.id, s.product_id, s.account_id))

    expected = summary[metric]
    if metric in {"cogs", "commission", "logistics", "advertising", "expenses"}:
        expected = -expected
    actual = sum(x["amount"] for x in rows)
    return {"metric": metric, "start": str(start), "end": str(end), "expected": expected, "explained": actual, "difference": expected - actual, "rows": sorted(rows, key=lambda x: (x["date"] or "", x["reference"]))}
