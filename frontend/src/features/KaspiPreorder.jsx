import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, FileSpreadsheet, LoaderCircle, RotateCcw, Search, Upload } from "lucide-react";
import { Empty, ErrorBox } from "../components/Feedback";

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const PAGE_SIZE = 50;

export default function KaspiPreorder({ ctx }) {
  const workerRef = useRef(null);
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("");
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [table, setTable] = useState(null);
  const [rows, setRows] = useState([]);
  const [dirty, setDirty] = useState({});
  const [accountId, setAccountId] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(() => new Set());
  const [page, setPage] = useState(1);
  const [bulkAction, setBulkAction] = useState("price-set");
  const [bulkValue, setBulkValue] = useState("");
  const [bulkPoint, setBulkPoint] = useState("all");

  useEffect(() => {
    const worker = new Worker(new URL("./kaspiPreorder.worker.js", import.meta.url), { type: "module" });
    workerRef.current = worker;
    worker.onmessage = ({ data }) => {
      if (data.type === "error") {
        setError(data.message || "Не удалось обработать файл.");
        setBusy(false);
        setMode("");
      } else if (data.type === "parsed") {
        setTable(data);
        setRows(data.rows);
        setDirty({});
        setSelected(new Set());
        setPage(1);
        setBusy(false);
        setMode("");
      } else if (data.type === "exported") {
        const blob = new Blob([data.buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "ACTIVE-preorder.xlsx";
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        setBusy(false);
        setMode("");
        setDirty({});
      }
    };
    worker.onerror = () => {
      setError("Не удалось открыть таблицу в браузере. Проверьте файл и попробуйте ещё раз.");
      setBusy(false);
      setMode("");
    };
    return () => {
      worker.terminate();
      workerRef.current = null;
    };
  }, []);

  const kaspiAccounts = useMemo(
    () => (ctx.refs.accounts || []).filter((account) => account.channel === "Kaspi" && account.active !== false),
    [ctx.refs.accounts],
  );
  const productMatches = useMemo(() => {
    const matches = new Map();
    for (const product of ctx.refs.products || []) {
      const key = String(product.sku || "").trim().toLowerCase();
      if (!key) continue;
      const list = matches.get(key) || [];
      list.push(product);
      matches.set(key, list);
    }
    return matches;
  }, [ctx.refs.products]);
  const scopedProductCounts = useMemo(() => {
    const account = kaspiAccounts.find((item) => String(item.id) === String(accountId));
    const counts = new Map();
    for (const [sku, list] of productMatches) {
      counts.set(sku, !account || !account.company_id
        ? list.length
        : list.filter((product) => !product.company_id || product.company_id === account.company_id).length);
    }
    return counts;
  }, [productMatches, kaspiAccounts, accountId]);

  const fileChange = useCallback((event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError("");
    if (!/\.xlsx$/i.test(file.name)) {
      setError("Загрузите оригинальный файл Kaspi в формате .xlsx.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("Файл больше 10 МБ. Выгрузите прайс-лист меньшего размера.");
      return;
    }
    setBusy(true);
    setMode("parse");
    setFileName(file.name);
    setTable(null);
    setRows([]);
    setDirty({});
    setSelected(new Set());
    workerRef.current?.postMessage({ type: "parse", file });
  }, []);

  const patchRow = (rowId, key, value, pointIndex = null) => {
    setRows((current) => current.map((row) => row.id === rowId
      ? { ...row, [key]: key === "stock" ? row.stock.map((old, index) => index === pointIndex ? value : old) : value }
      : row));
    setDirty((current) => {
      const next = { ...current };
      const edit = { ...(next[rowId] || {}) };
      if (key === "stock") edit.stock = { ...(edit.stock || {}), [pointIndex]: value };
      else edit[key] = value;
      next[rowId] = edit;
      return next;
    });
  };

  const applyBulk = () => {
    if (!selected.size || !table) return;
    const value = Number(String(bulkValue).replace(",", "."));
    if (["price-set", "preorder"].includes(bulkAction) && (!Number.isFinite(value) || value < 0)) {
      setError("Введите неотрицательное число для массового изменения.");
      return;
    }
    if (bulkAction === "price-percent" && (!Number.isFinite(value) || value < -100)) {
      setError("Укажите изменение цены от −100% и выше.");
      return;
    }
    setError("");
    const ids = selected;
    const pointIndexes = bulkPoint === "all" ? table.pointLabels.map((_, index) => index) : [Number(bulkPoint)];
    const updates = new Map();
    for (const row of rows) {
      if (!ids.has(row.id)) continue;
      const edit = {};
      if (bulkAction === "price-set") edit.price = Math.round(value);
      if (bulkAction === "price-percent") edit.price = Math.max(0, Math.round((row.price || 0) * (1 + value / 100)));
      if (bulkAction === "preorder") edit.preorder = Math.round(value);
      if (bulkAction === "stock-on" || bulkAction === "stock-off") {
        const stock = {};
        pointIndexes.forEach((index) => { stock[index] = bulkAction === "stock-on"; });
        edit.stock = stock;
      }
      updates.set(row.id, edit);
    }
    setRows((current) => current.map((row) => {
      const edit = updates.get(row.id);
      if (!edit) return row;
      const next = { ...row };
      if (Object.hasOwn(edit, "price")) next.price = edit.price;
      if (Object.hasOwn(edit, "preorder")) next.preorder = edit.preorder;
      if (edit.stock) next.stock = row.stock.map((old, index) => Object.hasOwn(edit.stock, index) ? edit.stock[index] : old);
      return next;
    }));
    setDirty((current) => {
      const next = { ...current };
      for (const [id, edit] of updates) {
        next[id] = { ...(next[id] || {}), ...edit,
          ...(edit.stock ? { stock: { ...(next[id]?.stock || {}), ...edit.stock } } : {}) };
      }
      return next;
    });
  };

  const visible = useMemo(() => {
    const text = query.trim().toLowerCase();
    return rows.filter((row) => {
      const matched = scopedProductCounts.get(row.sku.toLowerCase()) === 1;
      if (filter === "unmatched" && matched) return false;
      if (filter === "in-stock" && !row.stock.some(Boolean)) return false;
      if (filter === "out-stock" && row.stock.some(Boolean)) return false;
      if (filter === "preorder" && !(row.preorder > 0)) return false;
      return !text || `${row.sku} ${row.name} ${row.brand}`.toLowerCase().includes(text);
    });
  }, [rows, scopedProductCounts, query, filter]);
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const pageRows = visible.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const selectedMatches = useMemo(() => rows.filter((row) => scopedProductCounts.get(row.sku.toLowerCase()) === 1).length, [rows, scopedProductCounts]);

  const toggleVisible = () => setSelected((current) => {
    const next = new Set(current);
    const allSelected = pageRows.length > 0 && pageRows.every((row) => next.has(row.id));
    pageRows.forEach((row) => allSelected ? next.delete(row.id) : next.add(row.id));
    return next;
  });
  const exportFile = () => {
    const edits = Object.entries(dirty).map(([excelRow, edit]) => ({ excelRow: Number(excelRow), ...edit }));
    if (!edits.length) return;
    if (edits.some((edit) => Object.hasOwn(edit, "price") && (edit.price === "" || !Number.isFinite(Number(edit.price))))) {
      setError("У товаров с изменённой ценой должно быть указано числовое значение.");
      return;
    }
    setError("");
    setBusy(true);
    setMode("export");
    workerRef.current?.postMessage({ type: "export", edits });
  };
  const reset = () => {
    setTable(null);
    setRows([]);
    setDirty({});
    setSelected(new Set());
    setFileName("");
    setError("");
    setPage(1);
  };

  return (
    <section className="kaspi-preorder">
      <div className="section-heading">
        <div><span className="eyebrow">KASPI · ACTIVE.XLSX</span><h2>Цены, наличие и предзаказ</h2><p>Правки остаются в браузере. Вы скачиваете готовый файл и загружаете его в кабинет Kaspi.</p></div>
        {table && <div className="kaspi-preorder-actions">
          <button type="button" className="secondary" onClick={reset}><RotateCcw size={16}/>Другой файл</button>
          <button type="button" className="primary" onClick={exportFile} disabled={busy || !Object.keys(dirty).length}><Download size={16}/>{busy && mode === "export" ? "Готовим файл…" : `Скачать изменения · ${Object.keys(dirty).length}`}</button>
        </div>}
      </div>
      <ErrorBox error={error}/>
      {!table ? <div className="panel padded kaspi-preorder-upload">
        <div className="kaspi-preorder-upload-icon"><FileSpreadsheet size={28}/></div>
        <h3>{busy && mode === "parse" ? "Открываем прайс-лист…" : "Загрузите ACTIVE.xlsx из Kaspi"}</h3>
        <p className="muted">Файл обрабатывается в отдельном потоке браузера: интерфейс остаётся отзывчивым. Максимум 10 МБ и 20 000 строк.</p>
        <button type="button" className="primary" disabled={busy} onClick={() => inputRef.current?.click()}>{busy ? <LoaderCircle className="spin" size={18}/> : <Upload size={18}/>}Выбрать файл</button>
        <input ref={inputRef} type="file" accept=".xlsx" hidden onChange={fileChange}/>
        <small>Поддерживается оригинальный Excel-файл Kaspi (.xlsx). Файл не отправляется в QOR и не сохраняется на сервере.</small>
      </div> : <>
        <div className="kaspi-preorder-toolbar panel">
          <div className="kaspi-preorder-file"><FileSpreadsheet size={20}/><div><b>{fileName}</b><small>{table.total.toLocaleString("ru-RU")} товаров · строка заголовков {table.headerRow} · лист «{table.sheetName}»</small></div></div>
          <div className="kaspi-preorder-selects">
            {kaspiAccounts.length > 0 && <label>Магазин QOR<select value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">Не выбирать</option>{kaspiAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>}
            {table.sheetNames.length > 1 && <label>Лист Excel<select value={table.sheetName} disabled={busy} onChange={(event) => {setBusy(true); setMode("parse"); workerRef.current?.postMessage({type:"select-sheet",sheetName:event.target.value});}}>{table.sheetNames.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>}
            <label className="kaspi-preorder-search"><Search size={17}/><input value={query} placeholder="Поиск по SKU и названию" onChange={(event) => {setQuery(event.target.value); setPage(1);}}/></label>
          </div>
        </div>
        {!!table.warnings.length && <div className="kaspi-preorder-warnings">{table.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
        {kaspiAccounts.length > 0 && accountId && <p className="kaspi-preorder-match-note">Совпало с каталогом выбранной компании: <b>{selectedMatches.toLocaleString("ru-RU")}</b> из {rows.length.toLocaleString("ru-RU")}. Несопоставленные строки не удаляются и попадут в скачанный файл без изменений.</p>}
        <div className="kaspi-preorder-bulk panel">
          <div><b>Массовое изменение</b><small>Выбрано: {selected.size.toLocaleString("ru-RU")} · выберите строки на текущей странице</small></div>
          <div className="kaspi-preorder-bulk-controls">
            <select value={bulkAction} onChange={(event) => setBulkAction(event.target.value)}>
              <option value="price-set">Задать цену</option><option value="price-percent">Изменить цену на %</option><option value="preorder">Срок предзаказа, дней</option><option value="stock-on">Включить наличие</option><option value="stock-off">Выключить наличие</option>
            </select>
            {bulkAction.startsWith("stock-") ? <select value={bulkPoint} onChange={(event) => setBulkPoint(event.target.value)}><option value="all">Все точки</option>{table.pointLabels.map((label,index)=><option key={label} value={index}>{label}</option>)}</select> : <input type="number" min={bulkAction === "price-percent" ? "-100" : "0"} step="1" value={bulkValue} placeholder={bulkAction === "price-percent" ? "например, -10" : "Значение"} onChange={(event) => setBulkValue(event.target.value)}/>}
            <button type="button" className="secondary" disabled={!selected.size || (bulkAction.startsWith("stock-") && !table.pointLabels.length)} onClick={applyBulk}>Применить к выбранным</button>
          </div>
        </div>
        <div className="kaspi-preorder-filters">
          {[["all","Все"],["unmatched","Нет в каталоге QOR"],["in-stock","Есть в наличии"],["out-stock","Нет в наличии"],["preorder","С предзаказом"]].map(([id,label])=><button type="button" key={id} className={filter===id?"active":""} onClick={()=>{setFilter(id);setPage(1);}}>{label}</button>)}
          <button type="button" className="secondary kaspi-select-page" onClick={toggleVisible} disabled={!pageRows.length}>{pageRows.length && pageRows.every((row)=>selected.has(row.id))?"Снять выбор страницы":"Выбрать страницу"}</button>
        </div>
        {!visible.length ? <Empty text="По этому фильтру товаров нет."/> : <div className="panel kaspi-preorder-table-wrap"><div className="kaspi-preorder-table-scroll"><table className="data-table kaspi-preorder-table"><thead><tr><th>Выбор</th><th>SKU</th><th>Товар</th><th>Бренд</th><th className="numeric">Цена · ₸</th>{table.pointLabels.map((label)=><th key={label}>{label}</th>)}<th>Предзаказ · дней</th><th>Каталог QOR</th></tr></thead><tbody>{pageRows.map((row)=>{
          const matchCount=scopedProductCounts.get(row.sku.toLowerCase())||0;
          const matched=matchCount===1;
          return <tr key={row.id}>
            <td><input type="checkbox" aria-label={`Выбрать SKU ${row.sku}`} checked={selected.has(row.id)} onChange={()=>setSelected((current)=>{const next=new Set(current);next.has(row.id)?next.delete(row.id):next.add(row.id);return next;})}/></td>
            <td className="strong">{row.sku}</td><td className="kaspi-preorder-name" title={row.name}>{row.name||"—"}</td><td>{row.brand||"—"}</td>
            <td><input className="kaspi-preorder-number" type="number" min="0" step="1" aria-label={`Цена ${row.sku}`} value={row.price ?? ""} onChange={(event)=>patchRow(row.id,"price",event.target.value===""?"":Math.max(0,Number(event.target.value)))}/></td>
            {row.stock.map((value,index)=><td key={table.pointLabels[index]}><button type="button" aria-pressed={value===true} aria-label={`${table.pointLabels[index]} ${row.sku}: ${value===true?"в наличии":"нет в наличии"}`} className={`kaspi-stock-toggle ${value===true?"on":value===false?"off":"unknown"}`} onClick={()=>patchRow(row.id,"stock",value!==true,index)}>{value===true?"Да":value===false?"Нет":"—"}</button></td>)}
            <td><input className="kaspi-preorder-number short" type="number" min="0" step="1" aria-label={`Предзаказ ${row.sku}`} value={row.preorder} onChange={(event)=>patchRow(row.id,"preorder",Math.max(0,Math.round(Number(event.target.value)||0)))}/></td>
            <td><span className={`kaspi-match ${matched?"matched":"unmatched"}`}>{matched?"Найден":matchCount>1?"Несколько":"Не найден"}</span></td>
          </tr>;
        })}</tbody></table></div>
        <div className="kaspi-preorder-pagination"><span>{visible.length.toLocaleString("ru-RU")} строк · страница {page} из {pageCount}</span><div><button type="button" className="secondary" disabled={page<=1} onClick={()=>setPage((p)=>Math.max(1,p-1))}>Назад</button><button type="button" className="secondary" disabled={page>=pageCount} onClick={()=>setPage((p)=>Math.min(pageCount,p+1))}>Далее</button></div></div></div>}
        <p className="kaspi-preorder-footnote">Изменения затрагивают только скачиваемый файл. QOR не публикует цены и остатки в Kaspi автоматически. Исходный файл остаётся неизменным.</p>
      </>}
    </section>
  );
}
