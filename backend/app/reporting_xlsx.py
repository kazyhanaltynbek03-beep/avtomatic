import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.chart import LineChart, Reference
from openpyxl.utils import get_column_letter

NAVY='172033'; BLUE='2563EB'; LIGHT='F3F6FA'; GREEN='DCFCE7'; RED='FEE2E2'; MUTED='64748B'; WHITE='FFFFFF'
MONEY_FMT='#,##0.00 "₸";[Red]-#,##0.00 "₸"'
INT_FMT='#,##0'
PCT_FMT='0.00%'


def _money(v):
    return None if v is None else v / 100


def _safe_text(v):
    if v is None: return ''
    s=str(v)
    return "'"+s if s.lstrip().startswith(('=','+','-','@')) else s


def _title(ws, title, subtitle=''):
    ws.sheet_view.showGridLines=False
    ws.merge_cells('A1:H1'); ws['A1']=title
    ws['A1'].font=Font(size=20,bold=True,color=WHITE); ws['A1'].fill=PatternFill('solid',fgColor=NAVY)
    ws['A1'].alignment=Alignment(vertical='center'); ws.row_dimensions[1].height=34
    ws.merge_cells('A2:H2'); ws['A2']=subtitle
    ws['A2'].font=Font(size=10,color=MUTED); ws.row_dimensions[2].height=22


def _header(ws,row,cols):
    for i,v in enumerate(cols,1):
        c=ws.cell(row,i,_safe_text(v)); c.font=Font(bold=True,color=WHITE); c.fill=PatternFill('solid',fgColor=BLUE); c.alignment=Alignment(vertical='center')
    ws.row_dimensions[row].height=22


def _fit(ws, widths=None):
    widths=widths or {}
    for i in range(1,ws.max_column+1):
        letter=get_column_letter(i)
        if letter in widths: ws.column_dimensions[letter].width=widths[letter]; continue
        maxlen=0
        for cell in ws[letter][:min(ws.max_row,250)]:
            maxlen=max(maxlen,len(str(cell.value or '')))
        ws.column_dimensions[letter].width=min(max(maxlen+2,11),32)
    ws.freeze_panes='A4'
    ws.auto_filter.ref=ws.dimensions if ws.max_row>=4 else None


def executive_workbook(report, start, end, scope_note=''):
    """Create a presentation-ready workbook from authoritative backend totals.

    Financial values are written from the deterministic finance engine. Excel is
    a reporting surface, not the accounting engine. The Control sheet repeats
    accounting identities so a reviewer can spot inconsistencies immediately.
    """
    wb=Workbook(); ws=wb.active; ws.title='Dashboard'
    _title(ws,'QOR • Business Report',f'{start} — {end} · {scope_note or report.get("scope_note","")}')
    kpis=[
        ('Выручка',_money(report['revenue'])),('Валовая прибыль',_money(report['gross_profit'])),
        ('Чистая прибыль',_money(report['net_profit'])),('Деньги на конец',_money(report['cash_closing'])),
        ('COGS',_money(report['cogs'])),('Расходы',_money(report['expenses'])),
        ('Реклама',_money(report['advertising'])),('Стоимость склада',_money(report['stock_value'])),
        ('B2B дебиторка',_money(report['b2b_debt'])),('Возвраты',_money(report['returns'])),
    ]
    r=4
    for idx,(label,value) in enumerate(kpis):
        col=1+(idx%2)*4; row=r+(idx//2)*2
        ws.cell(row,col,label).font=Font(size=10,color=MUTED,bold=True)
        ws.merge_cells(start_row=row+1,start_column=col,end_row=row+1,end_column=col+2)
        c=ws.cell(row+1,col,value); c.number_format=MONEY_FMT; c.font=Font(size=16,bold=True,color=NAVY)
        c.fill=PatternFill('solid',fgColor=LIGHT)
    ws['A15']='Методика'; ws['A15'].font=Font(bold=True,color=NAVY); ws.merge_cells('B15:H15'); ws['B15']=report.get('method','')
    ws['A16']='Единица'; ws['A16'].font=Font(bold=True,color=NAVY); ws.merge_cells('B16:H16'); ws['B16']='Все суммы отображаются в KZT; источник расчётов — backend QOR.'
    _fit(ws,{'A':20,'B':18,'C':18,'D':4,'E':20,'F':18,'G':18,'H':4})

    # P&L
    ws=wb.create_sheet('P&L'); _title(ws,'P&L','Начисление: продажи и возвраты периода; общие расходы не распределяются по SKU без правила.')
    _header(ws,4,['Показатель','Сумма, ₸'])
    pnl=[('Выручка',report['revenue']),('COGS',report['cogs']),('Валовая прибыль',report['gross_profit']),('Комиссии',report['commission']),('Логистика',report['logistics']),('Реклама',report['advertising']),('Операционные расходы',report['expenses']),('Чистая прибыль',report['net_profit'])]
    for i,(name,val) in enumerate(pnl,5): ws.cell(i,1,name); ws.cell(i,2,_money(val)).number_format=MONEY_FMT
    ws['A14']='Маржа'; ws['B14']=(report['margin']/100 if report['margin'] is not None else None); ws['B14'].number_format=PCT_FMT
    ws['A15']='ROI'; ws['B15']=(report['roi']/100 if report['roi'] is not None else None); ws['B15'].number_format=PCT_FMT
    _fit(ws,{'A':28,'B':20})

    # Cash Flow
    ws=wb.create_sheet('Cash Flow'); _title(ws,'Cash Flow','Движение денег отдельно от прибыли.')
    _header(ws,4,['Показатель','Сумма, ₸'])
    cash=[('Остаток на начало',report['cash_opening']),('Поступления',report['cash_inflow']),('Выплаты',report['cash_outflow']),('Чистый поток',report['cash_flow']),('Остаток на конец',report['cash_closing'])]
    for i,(name,val) in enumerate(cash,5): ws.cell(i,1,name); ws.cell(i,2,_money(val)).number_format=MONEY_FMT
    _header(ws,12,['Категория','Поступления, ₸','Выплаты, ₸','Net, ₸'])
    for i,x in enumerate(report.get('cash_by_category',[]),13):
        ws.cell(i,1,_safe_text(x['category'])); ws.cell(i,2,_money(x['inflow'])); ws.cell(i,3,_money(x['outflow'])); ws.cell(i,4,_money(x['net']))
        for j in range(2,5): ws.cell(i,j).number_format=MONEY_FMT
    _fit(ws,{'A':28,'B':20,'C':20,'D':20})

    # Sales by channel
    ws=wb.create_sheet('Продажи'); _title(ws,'Продажи по каналам','Kaspi / Wildberries / Ozon / Offline / B2B и подключённые аккаунты.')
    _header(ws,4,['Канал','Выручка, ₸','COGS, ₸','Прямые затраты, ₸','Прибыль, ₸','Количество'])
    for i,x in enumerate(report.get('channel_summary',[]),5):
        vals=[_safe_text(x['channel']),_money(x['revenue']),_money(x['cogs']),_money(x['costs']),_money(x['profit']),x['quantity']]
        for j,v in enumerate(vals,1): ws.cell(i,j,v)
        for j in range(2,6): ws.cell(i,j).number_format=MONEY_FMT
        ws.cell(i,6).number_format=INT_FMT
    _fit(ws,{'A':22,'B':18,'C':18,'D':20,'E':18,'F':14})

    # Stock
    ws=wb.create_sheet('Склад'); _title(ws,'Склад','Фактический остаток и стоимость по движениям ERP.')
    _header(ws,4,['SKU','Товар','Количество','Стоимость, ₸','Min stock','Продано','Статус'])
    for i,x in enumerate(report.get('stock',[]),5):
        status='Ниже минимума' if x['quantity']<=x['min_stock'] else ('Нет продаж' if x['quantity']>0 and x['sold']<=0 else 'OK')
        vals=[_safe_text(x['sku']),_safe_text(x['name']),x['quantity'],_money(x['value']),x['min_stock'],x['sold'],status]
        for j,v in enumerate(vals,1): ws.cell(i,j,v)
        ws.cell(i,4).number_format=MONEY_FMT
        if status!='OK': ws.cell(i,7).fill=PatternFill('solid',fgColor=RED)
    _fit(ws,{'A':18,'B':34,'C':14,'D':20,'E':14,'F':14,'G':18})

    # Daily + chart
    ws=wb.create_sheet('Динамика'); _title(ws,'Динамика','Дневная выручка и прибыль за выбранный период.')
    _header(ws,4,['Дата','Выручка, ₸','Прибыль, ₸'])
    for i,x in enumerate(report.get('daily',[]),5):
        ws.cell(i,1,_safe_text(x['date'])); ws.cell(i,2,_money(x['revenue'])); ws.cell(i,3,_money(x['profit']))
        ws.cell(i,2).number_format=MONEY_FMT; ws.cell(i,3).number_format=MONEY_FMT
    if report.get('daily'):
        chart=LineChart(); chart.title='Выручка и прибыль'; chart.y_axis.title='KZT'; chart.x_axis.title='Дата'; chart.height=8; chart.width=16
        chart.add_data(Reference(ws,min_col=2,max_col=3,min_row=4,max_row=4+len(report['daily'])),titles_from_data=True)
        chart.set_categories(Reference(ws,min_col=1,min_row=5,max_row=4+len(report['daily'])))
        ws.add_chart(chart,'E4')
    _fit(ws,{'A':16,'B':20,'C':20})

    # Control / reconciliation
    ws=wb.create_sheet('Контроль'); _title(ws,'Контроль расчётов','Автоматические бухгалтерские тождества. PASS означает, что агрегаты согласованы.')
    _header(ws,4,['Проверка','Левая часть, ₸','Правая часть, ₸','Разница, ₸','Статус'])
    checks=[
        ('Валовая прибыль = Выручка − COGS',report['gross_profit'],None if report['cogs'] is None else report['revenue']-report['cogs']),
        ('Чистая прибыль = GP − комиссии − логистика − реклама − расходы',report['net_profit'],None if report['gross_profit'] is None else report['gross_profit']-report['commission']-report['logistics']-report['advertising']-report['expenses']),
        ('Cash closing = opening + inflow − outflow',report['cash_closing'],report['cash_opening']+report['cash_inflow']-report['cash_outflow']),
        ('Cash flow = inflow − outflow',report['cash_flow'],report['cash_inflow']-report['cash_outflow']),
    ]
    for i,(name,left,right) in enumerate(checks,5):
        diff=None if left is None or right is None else left-right; vals=[name,_money(left),_money(right),_money(diff),'COGS_PENDING' if diff is None else ('PASS' if diff==0 else 'FAIL')]
        for j,v in enumerate(vals,1): ws.cell(i,j,v)
        for j in range(2,5): ws.cell(i,j).number_format=MONEY_FMT
        ws.cell(i,5).fill=PatternFill('solid',fgColor=GREEN if diff==0 else RED); ws.cell(i,5).font=Font(bold=True)
    ws['A11']='Важно'; ws['A11'].font=Font(bold=True,color=NAVY); ws.merge_cells('B11:H12'); ws['B11']='Excel не является источником бухгалтерской истины. Финансовые итоги рассчитаны сервером QOR и выгружены как значения. Формулы из импортируемых XLSX блокируются.'; ws['B11'].alignment=Alignment(wrap_text=True,vertical='top')
    _fit(ws,{'A':58,'B':20,'C':20,'D':18,'E':12})

    # protect calculated/report sheets from accidental edits without a password barrier
    for ws in wb.worksheets:
        ws.sheet_properties.pageSetUpPr.fitToPage=True
        ws.page_setup.fitToWidth=1; ws.page_setup.fitToHeight=0
        ws.oddFooter.center.text='QOR AI BUSINESS ERP'
        ws.oddFooter.right.text='Page &P of &N'
    out=io.BytesIO(); wb.save(out); return out.getvalue()
