from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from . import schemas as s, finance as f
from .models import AIAction, AIActionPlan, Product, Counterparty, GeneratedDocument, ProductCardVersion, Account, MarketplaceProductMapping, MarketplaceProductCost
from .security import require, scope, audit
from sqlalchemy import select, func
from .product_studio import assess_performance, next_experiment

OPERATION_ACTIONS={"post_purchase":(s.PurchaseIn,f.purchase,"inventory"),"post_sale":(s.SaleIn,f.sale,"sales"),"post_return":(s.ReturnIn,f.return_sale,"sales"),"post_expense":(s.ExpenseIn,f.expense,"finance"),"post_cash":(s.CashIn,f.payment,"finance"),"post_adjustment":(s.AdjustIn,f.adjust,"inventory")}
MASTER_ACTIONS={"create_product":(Product,s.ProductIn,"catalog"),"create_counterparty":(Counterparty,s.CounterpartyIn,"finance"),"create_document":(GeneratedDocument,s.GeneratedDocumentIn,"documents")}
def catalog(): return {"post_purchase":"Провести закуп","post_sale":"Провести продажу","post_return":"Провести возврат","post_expense":"Провести расход","post_cash":"Провести движение денег","post_adjustment":"Корректировать склад","create_product":"Создать товар","set_marketplace_cost":"Установить себестоимость товара","create_counterparty":"Создать контрагента","create_document":"Создать документ","create_product_card":"Создать версию карточки товара","validate_product_card":"Проверить карточку marketplace","prepare_product_card_publish":"Подготовить карточку к публикации","optimize_product_card":"Создать следующую оптимизационную версию"}

def _validate_marketplace_cost(db, user, payload):
    require(user, "finance", True)
    try:
        account = db.get(Account, int(payload.get("account_id") or 0))
        product = db.get(Product, int(payload.get("product_id") or 0))
        cost = Decimal(str(payload.get("unit_cost"))).quantize(Decimal("0.01"))
        effective_from = date.fromisoformat(str(payload.get("effective_from")))
    except (TypeError, ValueError, InvalidOperation, ArithmeticError):
        raise HTTPException(422, "Нужны магазин, товар, себестоимость и дата начала действия")
    if not account or not account.active or account.channel not in {"Kaspi", "Wildberries", "Ozon"}:
        raise HTTPException(404, "Активный магазин маркетплейса не найден")
    if not product or not product.active:
        raise HTTPException(404, "Активный товар не найден")
    scope(user, account.company_id)
    if not cost.is_finite() or cost <= 0 or cost > Decimal("1000000000000"):
        raise HTTPException(422, "Себестоимость должна быть больше нуля")
    mappings = db.scalars(select(MarketplaceProductMapping).where(
        MarketplaceProductMapping.account_id == account.id,
        MarketplaceProductMapping.company_id == account.company_id,
        MarketplaceProductMapping.product_id == product.id,
    )).all()
    if not mappings:
        raise HTTPException(422, "Товар не сопоставлен с карточкой этого магазина. Сначала выполните сопоставление.")
    return {"account_id": account.id, "account_name": account.name, "channel": account.channel,
            "product_id": product.id, "product_name": product.name, "product_sku": product.sku,
            "company_id": account.company_id,
            "unit_cost": str(cost), "effective_from": effective_from.isoformat(),
            "external_keys": [m.external_key for m in mappings]}, account.company_id

def _card_validate(db, card):
    product=db.get(Product,card.product_id); errors=[]
    if not product: errors.append("Товар не найден")
    if not (card.title or "").strip(): errors.append("Название обязательно")
    if not (card.description or "").strip(): errors.append("Описание обязательно")
    if not card.image_document_ids: errors.append("Нужно минимум одно изображение товара")
    if card.marketplace not in {"kaspi","wildberries","ozon"}: errors.append("Неподдерживаемый marketplace")
    facts={"brand":getattr(product,"brand",None),"country":getattr(product,"country",None),"weight":getattr(product,"weight_g",None),"volume":getattr(product,"volume_cm3",None)} if product else {}
    for key,val in (card.characteristics or {}).items():
        if key in facts and facts[key] in (None,""): errors.append(f"{key}: характеристика не подтверждена ERP")
        elif key in facts and str(val).strip()!=str(facts[key]).strip(): errors.append(f"{key}: значение не совпадает с ERP")
    return {"marketplace":card.marketplace,"passed":not errors,"errors":errors,"warnings":[],"checked_at":datetime.now(timezone.utc).isoformat(),"rule_set":"qor-marketplace-safe-v1","note":"Финальная модерация выполняется marketplace; QOR не гарантирует принятие площадкой."}

def _validate_card_action(db,user,kind,payload):
    if kind=="create_product_card":
        require(user,"marketing",True); pid=int(payload.get("product_id") or 0); product=db.get(Product,pid)
        if not product: raise HTTPException(404,"Товар не найден")
        cid=int(payload.get("company_id") or 0)
        if not cid: raise HTTPException(422,"company_id обязателен для карточки")
        scope(user,cid)
        mp=str(payload.get("marketplace","kaspi")).lower(); prev=db.scalar(select(func.max(ProductCardVersion.version)).where(ProductCardVersion.product_id==pid,ProductCardVersion.marketplace==mp)) or 0
        normalized={"company_id":cid,"product_id":pid,"marketplace":mp,"version":prev+1,"title":str(payload.get("title") or product.name)[:240],"description":str(payload.get("description") or ""),"characteristics":payload.get("characteristics") or {},"image_document_ids":[int(x) for x in payload.get("image_document_ids",[])],"parent_version_id":payload.get("parent_version_id")}
        return normalized,cid
    require(user,"marketing",True); card=db.get(ProductCardVersion,int(payload.get("card_id") or 0))
    if not card: raise HTTPException(404,"Карточка не найдена")
    scope(user,card.company_id); normalized={"card_id":card.id}
    if kind=="prepare_product_card_publish":
        normalized.update({"review_days":max(1,int(payload.get("review_days",7))),"auto_optimize":bool(payload.get("auto_optimize",True)),"auto_publish":bool(payload.get("auto_publish",False)),"rollback":bool(payload.get("rollback",True)),"max_generations":max(1,min(10,int(payload.get("max_generations",3))))})
    return normalized,card.company_id
def _validate(db,user,kind,payload):
    if kind in OPERATION_ACTIONS:
        schema,_,cap=OPERATION_ACTIONS[kind]; require(user,cap,True); obj=schema.model_validate(payload)
    elif kind in MASTER_ACTIONS:
        _,schema,cap=MASTER_ACTIONS[kind]; require(user,cap,True); obj=schema.model_validate(payload)
    elif kind == "set_marketplace_cost":
        return _validate_marketplace_cost(db,user,payload)
    elif kind in {"create_product_card","validate_product_card","prepare_product_card_publish","optimize_product_card"}:
        return _validate_card_action(db,user,kind,payload)
    else: raise HTTPException(422,"Это действие AI не разрешено")
    cid=getattr(obj,"company_id",None)
    if cid: scope(user,cid)
    return obj,cid
def propose(db,user,kind,payload,thread_id=None,agent="rick"):
    obj,cid=_validate(db,user,kind,payload); normalized=obj if isinstance(obj,dict) else obj.model_dump(mode="json")
    warning = "Изменение ERP будет выполнено только после подтверждения пользователя."
    if kind == "set_marketplace_cost":
        warning += " Цена применяется только к продажам маркетплейса без FIFO-себестоимости с указанной даты; закупочные FIFO-партии и проведённые движения склада не переписываются."
    preview={"title":catalog()[kind],"action_type":kind,"payload":normalized,"requires_confirmation":True,"warning":warning}
    row=AIAction(user_id=user.id,company_id=cid,thread_id=thread_id,agent=agent,action_type=kind,payload=normalized,preview=preview,risk="high",status="pending")
    db.add(row); db.flush(); audit(db,user,"ai_action_proposed","ai_actions",row.id,{"type":kind}); db.commit(); db.refresh(row); return row
def execute(db,user,row):
    if row.user_id != user.id and user.role != "Owner": raise HTTPException(403,"Действие недоступно")
    if row.status != "pending": raise HTTPException(409,"Действие уже обработано")
    parsed,_=_validate(db,user,row.action_type,row.payload); row.confirmed_at=datetime.now(timezone.utc); row.status="confirmed"; db.flush()
    try:
        if row.action_type in OPERATION_ACTIONS: _,fn,_=OPERATION_ACTIONS[row.action_type]; result=fn(db,user,parsed)
        elif row.action_type == "set_marketplace_cost":
            p=parsed
            amount=int(Decimal(p["unit_cost"])*100)
            effective_from=date.fromisoformat(p["effective_from"])
            for external_key in p["external_keys"]:
                row_cost=db.scalar(select(MarketplaceProductCost).where(
                    MarketplaceProductCost.account_id==p["account_id"],
                    MarketplaceProductCost.external_key==external_key,
                    MarketplaceProductCost.effective_from==effective_from,
                ))
                if row_cost:
                    row_cost.unit_cost=amount; row_cost.updated_by=user.id
                else:
                    db.add(MarketplaceProductCost(company_id=p["company_id"],account_id=p["account_id"],
                        external_key=external_key,product_name=db.get(Product,p["product_id"]).name,
                        unit_cost=amount,currency="KZT",effective_from=effective_from,updated_by=user.id))
            db.flush()
            audit(db,user,"update","marketplace_product_costs",p["product_id"],{
                "account_id":p["account_id"],"unit_cost":p["unit_cost"],
                "effective_from":p["effective_from"],"external_keys":p["external_keys"]})
            result={"account_id":p["account_id"],"product_id":p["product_id"],
                "unit_cost":p["unit_cost"],"currency":"KZT",
                "product_name":p["product_name"],"product_sku":p["product_sku"],"store":p["account_name"],
                "effective_from":p["effective_from"],"external_keys":p["external_keys"]}
        elif row.action_type in MASTER_ACTIONS:
            model,_,_=MASTER_ACTIONS[row.action_type]; result=model(**parsed.model_dump()); db.add(result); db.flush()
        else:
            p=parsed if isinstance(parsed,dict) else parsed.model_dump()
            if row.action_type=="create_product_card":
                result=ProductCardVersion(**p); db.add(result); db.flush(); result.validation=_card_validate(db,result); result.status="validated" if result.validation["passed"] else "needs_fix"
            else:
                result=db.get(ProductCardVersion,p["card_id"])
                if row.action_type=="validate_product_card":
                    result.validation=_card_validate(db,result); result.status="validated" if result.validation["passed"] else "needs_fix"
                elif row.action_type=="prepare_product_card_publish":
                    result.validation=_card_validate(db,result)
                    if not result.validation["passed"]: raise HTTPException(422,"Карточка не прошла QOR Validator")
                    from datetime import timedelta
                    result.status="ready_for_publish"; result.review_after=datetime.now(timezone.utc)+timedelta(days=p["review_days"]); result.review_state="scheduled"; result.optimization_policy={k:p[k] for k in ("auto_optimize","auto_publish","rollback","review_days","max_generations")}
                elif row.action_type=="optimize_product_card":
                    assessment=assess_performance(result.metrics or {})
                    if assessment["decision"]=="insufficient_data": raise HTTPException(422,assessment["reason"])
                    prev=db.scalar(select(func.max(ProductCardVersion.version)).where(ProductCardVersion.product_id==result.product_id,ProductCardVersion.marketplace==result.marketplace)) or result.version
                    new=ProductCardVersion(company_id=result.company_id,product_id=result.product_id,marketplace=result.marketplace,version=prev+1,title=result.title,description=result.description,characteristics=result.characteristics,image_document_ids=result.image_document_ids,status="optimization_draft",parent_version_id=result.id,optimization_policy=result.optimization_policy or {},review_state="idle",validation={"passed":False,"errors":[],"warnings":[assessment["reason"]],"requires_ai_regeneration":True,"experiment":next_experiment(result.version)})
                    db.add(new); db.flush(); result=new
        row.result=jsonable_encoder(result if isinstance(result,dict) else {c.name:getattr(result,c.name) for c in result.__table__.columns if c.name not in ("password_hash","path")}); row.status="executed"; row.executed_at=datetime.now(timezone.utc)
        audit(db,user,"ai_action_executed","ai_actions",row.id,{"type":row.action_type,"result_id":getattr(result,"id",None)}); db.commit(); return row
    except Exception as exc:
        db.rollback(); failed=db.get(AIAction,row.id); failed.status="failed"; failed.error=str(exc)[:1000]; db.commit(); raise
def cancel(db,user,row):
    if row.user_id != user.id and user.role != "Owner": raise HTTPException(403,"Действие недоступно")
    if row.status != "pending": raise HTTPException(409,"Действие уже обработано")
    row.status="cancelled"; audit(db,user,"ai_action_cancelled","ai_actions",row.id,{"type":row.action_type}); db.commit(); return row

# Multi-step plans: one explicit approval can authorize a bounded sequence of already validated actions.
def propose_plan(db,user,title,goal,steps,thread_id=None,agent="rick"):
    from .models import AIActionPlan
    if not isinstance(steps,list) or not 1 <= len(steps) <= 20: raise HTTPException(422,"План должен содержать от 1 до 20 действий")
    normalized=[]; company_ids=set()
    # Validate every step before storing anything executable.
    for i,step in enumerate(steps,1):
        kind=str((step or {}).get("action_type", "")); payload=(step or {}).get("payload") or {}
        obj,cid=_validate(db,user,kind,payload); data=obj if isinstance(obj,dict) else obj.model_dump(mode="json")
        if cid: company_ids.add(cid)
        normalized.append({"order":i,"action_type":kind,"title":catalog()[kind],"payload":data,"status":"waiting"})
    if len(company_ids)>1: raise HTTPException(422,"Один AI-план не может изменять несколько компаний")
    cid=next(iter(company_ids),None)
    row=AIActionPlan(user_id=user.id,company_id=cid,thread_id=thread_id,agent=agent,title=str(title or "AI-план")[:180],goal=str(goal or "")[:4000],steps=normalized,status="pending",progress=0,result={})
    db.add(row); db.flush(); audit(db,user,"ai_plan_proposed","ai_action_plans",row.id,{"steps":len(normalized),"goal":row.goal[:300]}); db.commit(); db.refresh(row); return row

def execute_plan(db,user,plan):
    if plan.user_id != user.id and user.role != "Owner": raise HTTPException(403,"План недоступен")
    if plan.status != "pending": raise HTTPException(409,"План уже обработан")
    plan.status="running"; plan.confirmed_at=datetime.now(timezone.utc); db.commit()
    action_ids=[]; step_states=list(plan.steps or []); results=[]
    try:
        for idx,step in enumerate(step_states):
            action=propose(db,user,step["action_type"],step["payload"],plan.thread_id,plan.agent); action_ids.append(action.id)
            action=execute(db,user,action); results.append({"action_id":action.id,"action_type":action.action_type,"result":action.result})
            step_states[idx]={**step,"status":"executed","action_id":action.id}; plan=db.get(AIActionPlan,plan.id); plan.steps=list(step_states); plan.action_ids=list(action_ids); plan.progress=idx+1; db.commit()
        plan=db.get(AIActionPlan,plan.id); plan.status="executed"; plan.result={"steps":results,"completed":len(results)}; plan.executed_at=datetime.now(timezone.utc); audit(db,user,"ai_plan_executed","ai_action_plans",plan.id,{"steps":len(results)}); db.commit(); db.refresh(plan); return plan
    except Exception as exc:
        db.rollback(); plan=db.get(AIActionPlan,plan.id); plan.status="partial_failed" if plan.progress else "failed"; plan.action_ids=list(action_ids); plan.error=str(exc)[:1000]; plan.steps=step_states; audit(db,user,"ai_plan_failed","ai_action_plans",plan.id,{"progress":plan.progress,"error":plan.error[:300]}); db.commit(); raise

def cancel_plan(db,user,plan):
    if plan.user_id != user.id and user.role != "Owner": raise HTTPException(403,"План недоступен")
    if plan.status != "pending": raise HTTPException(409,"План уже обработан")
    plan.status="cancelled"; audit(db,user,"ai_plan_cancelled","ai_action_plans",plan.id,{"steps":len(plan.steps or [])}); db.commit(); db.refresh(plan); return plan
