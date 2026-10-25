from io import BytesIO
from openpyxl import Workbook
from app.wb_excel_reconciliation import parse_report

def test_wb_excel_preview_separates_sales_and_logistics():
    w=Workbook();s=w.active
    s.append(['Обоснование для оплаты','К перечислению Продавцу за реализованный Товар','Услуги по доставке товара покупателю','Кол-во'])
    s.append(['Продажа',100,0,1]);s.append(['Логистика',0,15,0])
    b=BytesIO();w.save(b)
    r=parse_report(b.getvalue())
    assert r['row_count']==2
    assert r['totals']['seller_for_pay']=='100'
    assert r['totals']['delivery']=='15'
    assert r['by_category']['sale']['quantity']=='1'
    assert r['by_category']['other']['delivery']=='15'

def test_client_workbook_baseline_2026_09_28_to_10_04():
    """Pin the attached client's 10-row report totals without storing raw seller data."""
    w=Workbook();s=w.active
    s.append(['Обоснование для оплаты','Цена розничная',
        'Цена розничная с учетом согласованной скидки','Вайлдберриз реализовал Товар (Пр)',
        'Вознаграждение с продаж до вычета услуг поверенного, без НДС',
        'Компенсация платёжных услуг/Комиссия за интеграцию платёжных сервисов',
        'Вознаграждение Вайлдберриз (ВВ), без НДС','НДС с Вознаграждения Вайлдберриз',
        'К перечислению Продавцу за реализованный Товар','Кол-во',
        'Услуги по доставке товара покупателю'])
    sales=[
        (63045.36,49895.15,1886.83,2434.86,1886.8275862068965,301.89,45271.57),
        (36360.89,30439.26,1164.26,1217.57,1164.2586206896551,186.28,27871.15),
        (69133.69,57376.70,-301.67,2799.96,-301.67241379310343,-48.27,54926.68),
        (69133.69,57376.70,-301.67,2799.96,-301.67241379310343,-48.27,54926.68),
        (68813.63,55397.64,1342.97,2215.90,1342.9741379310344,214.88,51623.89),
    ]
    for retail,realized,commission,acquiring,reward,vat,payable in sales:
        s.append(['Продажа',retail,retail,realized,commission,acquiring,reward,vat,payable,1,0])
    for delivery in [6114.24,6763.29,6208.05,6208.05,7403.54]:
        s.append(['Логистика',0,0,0,0,0,0,0,0,0,delivery])
    b=BytesIO();w.save(b)
    r=parse_report(b.getvalue())
    assert r['row_count']==10
    assert r['currency'] is None
    assert r['totals']['retail']=='306487.26'
    assert r['totals']['retail_after_agreed_discount']=='306487.26'
    assert r['totals']['wb_realized']=='250485.45'
    assert r['totals']['commission_before_agent']=='3790.72'
    assert r['totals']['acquiring']=='11468.25'
    assert r['totals']['commission_vat']=='606.51'
    assert r['totals']['seller_for_pay']=='234619.97'
    assert r['totals']['delivery']=='32697.17'
