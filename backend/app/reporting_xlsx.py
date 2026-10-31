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


def workbook_from_template(template_bytes, report, start, end, scope_note=''):
    """Keep a customer's XLSX layout, fill recognized totals, append QOR details."""
    from io import BytesIO
    from openpyxl import load_workbook

    aliases = {
        'revenue': ('выручка', 'оборот', 'түсім'),
        'gross_profit': ('валовая прибыль', 'gross profit', 'жалпы пайда'),
        'net_profit': ('чистая прибыль', 'net profit', 'таза пайда'),
        'commission': ('комиссия', 'комиссии', 'комиссия wb', 'комиссия kaspi'),
        'logistics': ('логистика', 'доставка', 'жеткізу'),
        'cogs': ('себестоимость', 'cogs', 'өзіндік құн'),
        'expenses': ('расходы', 'операционные расходы', 'шығындар'),
        'returns': ('возвраты', 'возвратов', 'қайтарым'),
        'cash_closing': ('остаток на конец', 'остаток денег', 'конечный остаток'),
        'cash_inflow': ('поступления', 'поступило', 'түсімдер'),
        'cash_outflow': ('выплаты', 'выплачено', 'төлемдер'),
    }
    values = {key: report.get(key) for key in aliases}
    for key, value in values.items():
        if value is not None:
            values[key] = value / 100

    try:
        wb = load_workbook(BytesIO(template_bytes))
    except Exception as exc:
        raise ValueError('Не удалось открыть Excel-образец') from exc
    filled = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if not isinstance(cell.value, str):
                    continue
                label = ' '.join(cell.value.casefold().replace('ё', 'е').split())
                metric = next((key for key, names in aliases.items()
                               if any(label == name or label.startswith(name + ':') for name in names)), None)
                if not metric or values.get(metric) is None:
                    continue
                right_edge = cell.column
                for merged in ws.merged_cells.ranges:
                    if merged.min_row <= cell.row <= merged.max_row and merged.min_col <= cell.column <= merged.max_col:
                        right_edge = max(right_edge, merged.max_col)
                target = None
                for col in range(right_edge + 1, right_edge + 5):
                    if any(r.min_row <= cell.row <= r.max_row and r.min_col <= col <= r.max_col for r in ws.merged_cells.ranges):
                        continue
                    candidate = ws.cell(cell.row, col)
                    if candidate.value in (None, '') or isinstance(candidate.value, (int, float)):
                        target = candidate
                        break
                if target is None:
                    continue
                target.value = values[metric]
                target.number_format = MONEY_FMT
                filled += 1
    if filled == 0:
        raise ValueError('Не нашёл в Excel-образце подписанные финансовые итоги для безопасного сопоставления.')

    # Preserve the customer's sheets and add the existing deterministic QOR report.
    details = load_workbook(BytesIO(executive_workbook(report, start, end, scope_note)))
    for source in details.worksheets:
        title = source.title[:31]
        if title in wb.sheetnames:
            title = ('QOR ' + title)[:31]
        dest = wb.create_sheet(title)
        for row in source.iter_rows():
            for cell in row:
                out_cell = dest.cell(cell.row, cell.column, cell.value)
                if cell.has_style:
                    out_cell._style = cell._style
                if cell.number_format:
                    out_cell.number_format = cell.number_format
        for key, dim in source.column_dimensions.items():
            dest.column_dimensions[key].width = dim.width
        dest.freeze_panes = source.freeze_panes
        dest.sheet_view.showGridLines = source.sheet_view.showGridLines
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def workbook_from_layout(report, start, end, layout):
    """Build a workbook using a Claude-extracted photo layout and ERP values only."""
    from io import BytesIO
    wb = Workbook()
    ws = wb.active
    ws.title = 'Отчёт'
    _title(ws, str(layout.get('title') or 'Отчёт по данным QOR')[:120], f'{start} — {end} · Источник цифр: ERP QOR')
    datasets = {
        'summary': [report],
        'products': report.get('products') or [],
        'stock': report.get('stock') or [],
        'daily': report.get('daily') or [],
        'channels': report.get('channel_summary') or [],
    }
    money_fields = {'revenue','gross_profit','net_profit','cogs','known_cogs','commission','logistics','advertising','expenses','returns','cash','cash_flow','cash_opening','cash_inflow','cash_outflow','cash_closing','value','costs','profit','contribution_profit'}
    row = 4
    for section in (layout.get('sections') or [])[:8]:
        title = str(section.get('title') or 'Данные')[:120]
        kind = section.get('kind')
        if kind not in datasets:
            continue
        ws.cell(row, 1, title).font = Font(size=13, bold=True, color=NAVY)
        row += 1
        columns = [c for c in (section.get('columns') or [])[:16] if c.get('field')]
        if kind == 'summary' and not columns:
            columns = [{'label': k.replace('_',' ').title(), 'field': k} for k in ('revenue','gross_profit','net_profit','cogs','commission','logistics','expenses')]
        _header(ws, row, [str(c.get('label') or c['field'])[:80] for c in columns])
        data = datasets[kind]
        for item in data[:2000]:
            row += 1
            for col_idx, column in enumerate(columns, 1):
                field = str(column.get('field') or '')
                value = item.get(field)
                if value is None and field in {'name', 'channel'}: value = item.get('name') or item.get('channel')
                if field in money_fields and value is not None:
                    value = value / 100
                cell = ws.cell(row, col_idx, _safe_text(value) if isinstance(value, str) else value)
                if field in money_fields: cell.number_format = MONEY_FMT
            if kind == 'summary':
                break
        row += 2
    if row <= 5:
        raise ValueError('На фото не получилось распознать структуру таблиц.')
    for col in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col)].width = min(max(16, max((len(str(ws.cell(r, col).value or '')) for r in range(1, min(ws.max_row, 40) + 1)), default=12) + 2), 34)
    ws.freeze_panes = 'A5'
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
