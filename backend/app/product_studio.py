from datetime import datetime, timezone

MIN_SAMPLE_VIEWS = 30


def assess_performance(metrics: dict, baseline: dict | None = None) -> dict:
    """Deterministic card review. AI may explain the result, but cannot invent KPIs."""
    m = metrics or {}
    views = int(m.get("views") or m.get("impressions") or 0)
    orders = int(m.get("orders") or 0)
    if views < MIN_SAMPLE_VIEWS:
        return {"decision":"insufficient_data","should_optimize":False,"reason":"Данные недостаточны для точного вывода","sample":{"views":views,"orders":orders}}
    conversion = float(m.get("conversion") if m.get("conversion") is not None else (orders / views * 100))
    b = baseline or {}
    bviews = int(b.get("views") or b.get("impressions") or 0)
    borders = int(b.get("orders") or 0)
    bconv = float(b.get("conversion") if b.get("conversion") is not None else (borders / bviews * 100 if bviews else 0))
    if bviews >= MIN_SAMPLE_VIEWS and bconv > 0:
        delta = (conversion - bconv) / bconv * 100
        if delta <= -10:
            return {"decision":"rollback","should_optimize":True,"reason":f"Конверсия хуже предыдущей версии на {abs(delta):.1f}%","conversion":round(conversion,3),"baseline_conversion":round(bconv,3),"delta_percent":round(delta,1)}
        if delta >= 10:
            return {"decision":"keep","should_optimize":False,"reason":f"Конверсия лучше предыдущей версии на {delta:.1f}%","conversion":round(conversion,3),"baseline_conversion":round(bconv,3),"delta_percent":round(delta,1)}
    if orders == 0 or conversion < 1.0:
        return {"decision":"optimize","should_optimize":True,"reason":"Низкая конверсия за контрольный период","conversion":round(conversion,3)}
    return {"decision":"keep","should_optimize":False,"reason":"Недостаточно оснований менять карточку","conversion":round(conversion,3)}


def next_experiment(version: int) -> dict:
    cycle = ((max(1, version) - 1) % 3) + 1
    if cycle == 1: return {"change":"main_image","label":"Главное фото","instruction":"Изменить только главное изображение; факты товара не менять."}
    if cycle == 2: return {"change":"visuals","label":"Фото + инфографика","instruction":"Улучшить визуал и инфографику только по подтверждённым характеристикам."}
    return {"change":"content","label":"Название и контент","instruction":"Оптимизировать название и описание без неподтверждённых характеристик."}
