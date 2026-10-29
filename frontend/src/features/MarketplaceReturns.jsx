import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, RefreshCw, ChevronLeft, ChevronRight, Clock3, CircleAlert, PackageCheck, Upload, FileSpreadsheet } from "lucide-react";
import { api } from "../services/api";
import { useLoad } from "../hooks/useLoad";
import { money } from "../utils/formatters";
import { ErrorBox, Spinner } from "../components/Feedback";
import { can } from "../utils/permissions";

const labels = {
  requested: "Заявка на возврат",
  returned: "Возвращён",
  financial_operation_reported: "Операция в финансовом отчёте",
  financial_return_confirmed: "Возврат из выписки",
  rejected: "Отклонён",
};
const showDate = (value) => value ? new Date(`${value}T12:00:00+06:00`).toLocaleDateString("ru-RU", { timeZone: "Asia/Almaty" }) : "Не подтверждено";
const returnAmount = (value) => value == null ? "Не подтверждено" : `−${money(value)}`;
const storeLabel = (store) => store?.store || store?.name || store?.account_name || store?.marketplace || "магазин";

function Metric({ title, value, caption, tone = "", onClick, active = false }) {
  return <button type="button" className={`returns-metric ${tone} ${active ? "selected" : ""}`} onClick={onClick} aria-pressed={active}>
    <span>{title}</span><strong>{value}</strong>{caption && <small>{caption}</small>}
  </button>;
}

function ReturnDetails({ item }) {
  return <details className="returns-detail"><summary>Подробности</summary><dl>
    <dt>Дата первоначального заказа</dt><dd>{showDate(item.order_date)}</dd>
    <dt>Дата выдачи</dt><dd>{showDate(item.issue_date)}</dd>
    <dt>Дата заявки</dt><dd>{showDate(item.request_date)}</dd>
    <dt>Дата финансовой операции</dt><dd>{showDate(item.financial_return_date)}</dd>
    <dt>Обнаружено системой</dt><dd>{showDate(item.detected_date)}</dd>
    <dt>Причина</dt><dd>{item.reason || "Не указана источником"}</dd>
    <dt>Экспертиза / дефект</dt><dd>{[item.examination, item.defect].filter(Boolean).join(" · ") || "Не зафиксировано"}</dd>
    <dt>Состояние товара</dt><dd>{item.item_condition === "unknown" ? "Не проверено" : item.item_condition}</dd>
    <dt>Источник</dt><dd>{item.source}</dd>
    <dt>Финансовый источник</dt><dd>{item.financial_source || item.source}</dd>
    <dt>Финансовая сверка</dt><dd>{item.accounted_status === "unverified" ? "Не подтверждено" : item.accounted_status === "yes" ? "Уже учтён" : "Не учтён"}</dd>
  </dl></details>;
}

const inventoryStatusLabels = {
  requested: "Возврат ожидает подтверждения",
  approved: "Возврат принят",
  in_transit: "В пути",
  received: "Получен · ожидает осмотра",
  inspection: "На проверке",
  restocked: "Пригоден · добавлен в остаток",
  defective: "Брак · недоступен для продажи",
  written_off: "Брак списан",
};
const inventoryNext = {
  requested: ["approved", "Подтвердить возврат"],
  approved: ["in_transit", "Отметить: в пути"],
  in_transit: ["received", "Отметить: получен"],
  received: ["inspection", "Начать проверку"],
  defective: ["written_off", "Списать брак"],
};

function InventoryAction({ item, onUpdated, allowInventory }) {
  const [match, setMatch] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const link = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const result = await api(`/marketplace-returns/${item.id}/inventory-match`, { method: "POST" });
      setMatch(result);
      if (!result.matched) setError(result.message);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const update = async (status) => {
    if (!match?.matched || busy) return;
    let reason = "";
    if (status === "defective" || status === "written_off") {
      reason = window.prompt(status === "defective" ? "Укажите причину брака" : "Укажите причину списания брака", "") || "";
      if (reason.trim().length < 3) { setError("Для фиксации брака нужна причина."); return; }
    }
    setBusy(true); setError("");
    try {
      const result = await api(`/returns/${match.return_id}/status`, { method: "POST", body: { status, reason } });
      setMatch((current) => ({ ...current, status: result.inventory_status || status }));
      onUpdated?.();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const next = match?.matched ? inventoryNext[match.status] : null;
  if (!allowInventory) return null;
  return <div className="returns-inventory-action" style={{ display: "grid", gap: 8, marginTop: 10, padding: "8px 0", borderTop: "1px solid #d9e3dd" }}>
    <strong>Единый склад</strong>
    {match?.matched ? <>
      <span>{inventoryStatusLabels[match.status] || match.status} · {match.quantity} шт.</span>
      {match.status === "inspection" ? <div className="returns-inventory-buttons" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button type="button" className="primary" disabled={busy} onClick={() => update("restocked")}>Пригоден · вернуть в остаток</button>
        <button type="button" className="secondary" disabled={busy} onClick={() => update("defective")}>Брак</button>
      </div> : next ? <button type="button" className="secondary" disabled={busy} onClick={() => update(next[0])}>{next[1]}</button> : null}
    </> : <button type="button" className="secondary" disabled={busy} onClick={link}>{busy ? "Проверяем…" : "Проверить связь со складом"}</button>}
    {error && <small role="status">{error}</small>}
  </div>;
}

function ReturnRow({ item, onUpdated, allowInventory }) {
  const title = item.product_name || "Товар не сопоставлен";
  return <>
    <tr className="returns-desktop-row">
      <td><span className={`returns-market ${item.marketplace.toLowerCase()}`}>{item.marketplace}</span><small className="returns-store">{item.store}</small></td>
      <td><strong>{item.order_id || "Не подтверждено"}</strong><small>{item.sku || "SKU не найден"}</small></td>
      <td className="returns-product-cell">{item.image_url ? <img src={item.image_url} alt="" loading="lazy"/> : <span className="returns-image-placeholder">□</span>}<span>{title}</span></td>
      <td>{item.quantity == null ? "Не подтверждено" : `${item.quantity} шт.`}</td>
      <td>{item.financial_return_date ? showDate(item.financial_return_date) : "Не подтверждено"}</td>
      <td>{item.amount == null || item.financial_status !== "confirmed" ? "Не подтверждено" : returnAmount(item.amount)}</td>
      <td><span className="returns-status">{labels[item.status] || item.status}</span><small className="returns-muted">{item.financial_status === "confirmed" ? "Финансы подтверждены" : "Ожидает финансового подтверждения"}</small><ReturnDetails item={item}/><InventoryAction item={item} onUpdated={onUpdated} allowInventory={allowInventory}/></td>
    </tr>
    <article className="returns-mobile-card">
      <header><span className={`returns-market ${item.marketplace.toLowerCase()}`}>{item.marketplace}</span><span className="returns-status">{labels[item.status] || item.status}</span></header>
      <div className="returns-mobile-product">{item.image_url ? <img src={item.image_url} alt="" loading="lazy"/> : <span className="returns-image-placeholder">□</span>}<div><strong>{title}</strong><small>{item.sku || "SKU не найден"} · {item.store}</small></div></div>
      <div className="returns-mobile-facts"><span>Заказ <b>{item.order_id || "Не подтверждено"}</b></span><span>Кол-во <b>{item.quantity == null ? "Не подтверждено" : `${item.quantity} шт.`}</b></span><span>Дата возврата <b>{showDate(item.financial_return_date)}</b></span><span>Сумма <b>{item.amount == null || item.financial_status !== "confirmed" ? "Не подтверждено" : returnAmount(item.amount)}</b></span></div>
      <ReturnDetails item={item}/><InventoryAction item={item} onUpdated={onUpdated} allowInventory={allowInventory}/>
    </article>
  </>;
}

export default function MarketplaceReturns({ ctx }) {
  const [marketplace, setMarketplace] = useState("all");
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [selectedMetric, setSelectedMetric] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [busyAccount, setBusyAccount] = useState(null);
  const [actionError, setActionError] = useState("");
  const [pollTick, setPollTick] = useState(0);
  const [listRefreshTick, setListRefreshTick] = useState(0);
  const [pendingAccounts, setPendingAccounts] = useState([]);
  const [statementFile, setStatementFile] = useState(null);
  const [statementAccount, setStatementAccount] = useState("");
  const [statementPreview, setStatementPreview] = useState(null);
  const [statementMapping, setStatementMapping] = useState({});
  const [statementBusy, setStatementBusy] = useState(false);
  const [statementMessage, setStatementMessage] = useState("");
  const fileRef = useRef(null);
  const lock = useRef(false);
  const autoStarted = useRef(new Set());
  const wasRunning = useRef(false);
  const notify = ctx.notify;
  const params = useMemo(() => {
    const p = new URLSearchParams({ marketplace, offset: String(offset), limit: "30", start: ctx.start, end: ctx.end, search });
    if (ctx.company) p.set("company_id", ctx.company);
    if (selectedAccountId) p.set("account_id", selectedAccountId);
    if (selectedMetric === "requests") p.set("return_status", "requested");
    if (selectedMetric === "confirmed" || selectedMetric === "confirmed_amount") p.set("financial_status", "confirmed");
    if (selectedMetric === "pending") p.set("financial_status", "unconfirmed");
    if (selectedMetric === "rejected") p.set("return_status", "rejected");
    if (selectedMetric === "unknown") p.set("unknown_only", "true");
    return p.toString();
  }, [marketplace, offset, ctx.start, ctx.end, ctx.company, search, selectedAccountId, selectedMetric]);
  const { data, error, loading } = useLoad(`/marketplace-returns?${params}`, `${ctx.refresh}:${listRefreshTick}`);
  const { data: syncData } = useLoad(`/marketplace-returns/sync-status${ctx.company ? `?company_id=${ctx.company}` : ""}`, `${ctx.refresh}:${pollTick}`);
  const records = data?.items || [];
  const summary = data?.summary || {};
  const stores = useMemo(() => data?.integrations || [], [data?.integrations]);
  const active = useMemo(() => stores.filter((x) => x.active && x.mode === "api"), [stores]);
  const autoEligible = useMemo(() => active.filter((x) => x.marketplace === "Kaspi" || x.marketplace === "Wildberries"), [active]);
  const progressByAccount = useMemo(() => Object.fromEntries((syncData?.items || []).map((x) => [x.account_id, x])), [syncData?.items]);

  useEffect(() => { setOffset(0); }, [marketplace, search, ctx.company, ctx.start, ctx.end, selectedAccountId, selectedMetric]);
  useEffect(() => { setSelectedAccountId(""); setSelectedMetric(""); }, [marketplace]);
  const syncRunning = (syncData?.items || []).some((x) => x.status === "running");
  useEffect(() => {
    if (!syncRunning && !pendingAccounts.length) return undefined;
    const timer = window.setInterval(() => setPollTick((n) => n + 1), 5000);
    return () => window.clearInterval(timer);
  }, [syncRunning, pendingAccounts.length]);

  useEffect(() => {
    const completed = pendingAccounts.filter(({ accountId, requestedAt }) => {
      const sync = progressByAccount[accountId];
      const startedAt = Date.parse(sync?.started_at || "");
      return Number.isFinite(startedAt) && startedAt >= requestedAt - 10000 && sync.status !== "running";
    });
    if (!completed.length) return;
    const completedIds = new Set(completed.map((x) => x.accountId));
    setPendingAccounts((current) => current.filter((x) => !completedIds.has(x.accountId)));
    setListRefreshTick((n) => n + 1);
  }, [pendingAccounts, progressByAccount]);

  useEffect(() => {
    if (wasRunning.current && !syncRunning && pendingAccounts.length === 0) {
      setListRefreshTick((n) => n + 1);
    }
    wasRunning.current = syncRunning;
  }, [syncRunning, pendingAccounts.length]);

  const discover = useCallback(async (accountId, silent = false) => {
    if (lock.current) return;
    lock.current = true;
    setBusyAccount(accountId);
    setActionError("");
    try {
      const requestedAt = Date.now();
      const result = await api("/marketplace-returns/discover", { method: "POST", body: { account_id: accountId } });
      if (!result?.already_running) {
        setPendingAccounts((current) => [...current.filter((x) => x.accountId !== Number(accountId)), { accountId: Number(accountId), requestedAt }]);
      }
      setPollTick((n) => n + 1);
      if (!silent) notify("Проверка сохранённых данных возвратов запущена");
    } catch (e) { setActionError(e.message); }
    finally { lock.current = false; setBusyAccount(null); }
  }, [notify]);
  useEffect(() => {
    if (!data || !syncData || !autoEligible.length) return;
    let cancelled = false;
    const startOnce = async () => {
      for (const store of autoEligible) {
        const accountId = Number(store.account_id);
        if (!accountId || autoStarted.current.has(accountId)) continue;
        autoStarted.current.add(accountId);
        if (progressByAccount[accountId]?.status === "running") continue;
        if (cancelled) return;
        await discover(accountId, true);
      }
    };
    startOnce();
    return () => { cancelled = true; };
  }, [data, syncData, autoEligible, progressByAccount, discover]);

  const previewStatement = async (file, accountId = statementAccount) => {
    if (!file || !accountId) return;
    setStatementBusy(true); setActionError(""); setStatementMessage(""); setStatementPreview(null);
    try {
      const form = new FormData(); form.append("file", file); form.append("account_id", accountId);
      const result = await api("/marketplace-returns/financial-statement/preview", { method:"POST", body:form });
      setStatementPreview(result); setStatementMapping(result.suggested_mapping || {});
    } catch (e) { setActionError(e.message); }
    finally { setStatementBusy(false); }
  };
  const importStatement = async () => {
    if (lock.current || !statementFile || !statementAccount) return;
    const required = ["external_return_id", "external_order_id", "financial_return_date", "amount"];
    if (required.some((key) => !statementMapping[key])) { setActionError("Сопоставьте ID возврата, исходный заказ, дату финансовой операции и сумму."); return; }
    lock.current = true; setStatementBusy(true); setActionError("");
    try {
      const form = new FormData(); form.append("file", statementFile); form.append("account_id", statementAccount); form.append("mapping", JSON.stringify(statementMapping));
      const result = await api("/marketplace-returns/financial-statement/import", { method:"POST", body:form });
      setStatementMessage(`Импортировано: ${result.imported}, связано с найденными возвратами: ${result.updated}${result.errors?.length ? `, строки с ошибками: ${result.errors.length}` : ""}.`);
      setStatementFile(null); setStatementPreview(null); setStatementMapping({}); setPollTick((n) => n + 1);
      if (fileRef.current) fileRef.current.value = "";
      ctx.notify("Выписка добавлена только в отдельный журнал возвратов");
    } catch (e) { setActionError(e.message); }
    finally { lock.current = false; setStatementBusy(false); }
  };
  const channelStores = marketplace === "all" ? active : active.filter((x) => x.marketplace === marketplace);
  const scopedStores = channelStores;
  const wbOrKaspiStores = channelStores.filter((x) => ["Kaspi", "Wildberries"].includes(x.marketplace));
  const pageCount = Math.ceil((data?.total || 0) / 30);
  const currentPage = Math.floor(offset / 30) + 1;
  const financeWrite = can(ctx.auth, "finance", true);
  const inventoryWrite = can(ctx.auth, "inventory", true);

  return <section className="marketplace-returns-page">
    <div className="returns-intro"><div><div className="eyebrow">ОПЕРАЦИИ · ИЗОЛИРОВАННЫЙ ЖУРНАЛ</div><h2>Возвраты маркетплейсов</h2><p>Финансовая сверка остаётся отдельной. Для склада возврат нужно сопоставить с исходной ERP-продажей, затем отметить получение и результат осмотра.</p></div>
      {wbOrKaspiStores.length > 0 && <div className="returns-sync-actions">{wbOrKaspiStores.map((store) => { const sync = progressByAccount[store.account_id]; const running = sync?.status === "running"; const resume = sync?.status === "partial"; return <button className="secondary returns-sync-button" key={store.account_id} disabled={Boolean(busyAccount || running)} onClick={() => discover(store.account_id)}><RefreshCw size={16} className={running ? "returns-spin" : ""}/>{busyAccount === store.account_id || running ? `Проверяем ${storeLabel(store)}` : resume ? `Продолжить ${storeLabel(store)} · ${sync.scanned}` : `Проверить ${storeLabel(store)}`}</button>; })}</div>}
    </div>
    {actionError && <ErrorBox error={actionError}/>}
    {financeWrite && <details className="returns-import-panel">
      <summary className="returns-import-heading"><FileSpreadsheet size={19}/><div><strong>Импорт финансовой выписки</strong><small>Раскройте, чтобы загрузить выписку Kaspi или Wildberries. Предпросмотр безопасен.</small></div><span className="returns-disclosure-icon" aria-hidden="true">⌄</span></summary>
      <div className="returns-import-controls">
        <label>Магазин<select value={statementAccount} onChange={(e) => { const value=e.target.value; setStatementAccount(value); setStatementPreview(null); if (statementFile && value) previewStatement(statementFile,value); }}><option value="">Выберите магазин</option>{active.map((store) => <option key={store.account_id} value={store.account_id}>{store.marketplace} · {storeLabel(store)}</option>)}</select></label>
        <label className="returns-file-picker"><Upload size={16}/><span>{statementFile?.name || "Выберите XLSX / CSV"}</span><input ref={fileRef} type="file" accept=".xlsx,.csv" onChange={(e) => { const file=e.target.files?.[0] || null; setStatementFile(file); if (file) previewStatement(file); }}/></label>
      </div>
      {statementBusy && <small className="returns-import-note">Читаем файл…</small>}
      {statementMessage && <div className="returns-import-success">{statementMessage}</div>}
      {statementPreview && <div className="returns-import-preview">
        <strong>{statementFile?.name} · {statementPreview.row_count} строк</strong>
        <div className="returns-mapping-grid">{[["external_return_id","ID возврата · обязательно"],["external_order_id","Исходный заказ · обязательно"],["financial_return_date","Дата операции · обязательно"],["amount","Сумма · обязательно"],["sku","Артикул / SKU"],["product_name","Название товара"],["quantity","Количество"],["reason","Причина"],["currency","Валюта"]].map(([key,label]) => <label key={key}>{label}<select value={statementMapping[key] || ""} onChange={(e) => setStatementMapping((old) => ({...old,[key]:e.target.value}))}><option value="">Не выбрано</option>{statementPreview.headers.map((header) => <option key={header} value={header}>{header}</option>)}</select></label>)}</div>
        {statementPreview.sample?.length > 0 && <div className="returns-sample-wrap"><table><thead><tr>{statementPreview.headers.map((h) => <th key={h}>{h}</th>)}</tr></thead><tbody>{statementPreview.sample.slice(0,3).map((row,i) => <tr key={i}>{statementPreview.headers.map((h) => <td key={h}>{String(row[h] ?? "")}</td>)}</tr>)}</tbody></table></div>}
        <small className="returns-import-note">Проверьте, что выбранная дата — дата фактической финансовой операции, а сумма относится к возврату покупателю.</small>
        <button type="button" className="primary" disabled={statementBusy || !statementAccount} onClick={importStatement}>Импортировать в отдельный журнал</button>
      </div>}
    </details>}
    <div className="returns-market-tabs" role="tablist" aria-label="Маркетплейс">
      {[ ["all", "Все"], ["Kaspi", "Kaspi"], ["Wildberries", "Wildberries"], ["Ozon", "Ozon"] ].map(([key, label]) => <button type="button" role="tab" aria-selected={marketplace === key} className={marketplace === key ? "active" : ""} key={key} onClick={() => setMarketplace(key)}>{label}</button>)}
    </div>
    {scopedStores.length > 0 && <div className="returns-store-tabs" role="group" aria-label="Магазин">
      <button type="button" className={!selectedAccountId ? "active" : ""} aria-pressed={!selectedAccountId} onClick={() => setSelectedAccountId("")}>Все магазины</button>
      {scopedStores.map((store) => <button type="button" key={store.account_id} className={String(selectedAccountId) === String(store.account_id) ? "active" : ""} aria-pressed={String(selectedAccountId) === String(store.account_id)} onClick={() => setSelectedAccountId(String(store.account_id))}>{storeLabel(store)}</button>)}
    </div>}
    {marketplace !== "all" && !stores.some((x) => x.marketplace === marketplace && x.active) && <div className="returns-empty-integration"><CircleAlert size={18}/><span>Интеграция {marketplace} не подключена. Данные возвратов не подставляются.</span></div>}
    {marketplace === "Ozon" && stores.some((x) => x.marketplace === "Ozon" && x.active) && <div className="returns-empty-integration"><CircleAlert size={18}/><span>Интеграция Ozon подключена, но обнаружение возвратов ещё не настроено.</span></div>}
    <div className="returns-filter-row"><label className="returns-search"><Search size={17}/><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Заказ, артикул, SKU, товар или магазин" aria-label="Поиск возвратов"/><button type="button" onClick={() => setSearch("")} aria-label="Очистить поиск">×</button></label><span className="returns-period-note">Период относится к дате заявки или подтверждённой финансовой операции.</span></div>
    <div className="returns-metrics-grid">
      <Metric title="Заявки на возврат" value={summary.requests || 0} caption="Не равны возврату денег" active={selectedMetric === "requests"} onClick={() => setSelectedMetric(selectedMetric === "requests" ? "" : "requests")}/>
      <Metric title="Подтверждённые возвраты" value={summary.confirmed_count || 0} caption="Финансовый источник подтвердил" tone="green" active={selectedMetric === "confirmed"} onClick={() => setSelectedMetric(selectedMetric === "confirmed" ? "" : "confirmed")}/>
      <Metric title="Сумма подтверждённых возвратов" value={summary.confirmed_amount ? returnAmount(summary.confirmed_amount) : "Не подтверждено"} caption="KZT · изолировано от отчётов" active={selectedMetric === "confirmed_amount"} onClick={() => setSelectedMetric(selectedMetric === "confirmed_amount" ? "" : "confirmed_amount")}/>
      <Metric title="На проверке" value={summary.pending_count || 0} caption="Дата или сумма могут отсутствовать" tone="amber" active={selectedMetric === "pending"} onClick={() => setSelectedMetric(selectedMetric === "pending" ? "" : "pending")}/>
      <Metric title="Отклонённые" value={summary.rejected_count || 0} active={selectedMetric === "rejected"} onClick={() => setSelectedMetric(selectedMetric === "rejected" ? "" : "rejected")}/>
      <Metric title="Не подтверждены дата или сумма" value={summary.unknown_count || 0} caption="Без подстановки даты синхронизации" tone="amber" active={selectedMetric === "unknown"} onClick={() => setSelectedMetric(selectedMetric === "unknown" ? "" : "unknown")}/>
    </div>
    <section className="returns-reconciliation"><div className="returns-reconciliation-title"><PackageCheck size={18}/><strong>Финансовая сверка возвратов</strong><span>Тестовый режим</span></div><div className="returns-reconciliation-grid"><div><small>Текущая сумма отчёта</small><strong>Требует выбора финансового источника</strong></div><div><small>Подтверждённые возвраты за период</small><strong>{summary.confirmed_amount ? returnAmount(summary.confirmed_amount) : "Не подтверждено"}</strong></div><div><small>Уже учтено / ещё не учтено</small><strong>{summary.accounted_amount || summary.not_accounted_amount ? `${money(summary.accounted_amount)} / ${money(summary.not_accounted_amount)}` : "Сверка не выполнена"}</strong></div><div><small>Отдельный скорректированный итог</small><strong>Не рассчитывается автоматически</strong></div></div><p>Автовычитание отключено: возврат не уменьшается повторно, если он уже есть в отчёте. Выручка, прибыль, выплата и денежный поток сверяются отдельно.</p></section>
    {loading && !data ? <Spinner/> : error ? <ErrorBox error={error}/> : records.length ? <>
      <div className="returns-table-wrap"><table className="returns-table"><thead><tr><th>Маркетплейс / магазин</th><th>Исходный заказ / SKU</th><th>Товар</th><th>Количество</th><th>Дата возврата</th><th>Сумма</th><th>Статус / сверка</th></tr></thead><tbody>{records.map((item) => <ReturnRow key={`${item.id}:${pollTick}`} item={item} onUpdated={() => setPollTick((n) => n + 1)} allowInventory={inventoryWrite}/>)}</tbody></table></div>
      <div className="returns-pagination"><span>{data.total} записей · страница {currentPage} из {Math.max(pageCount, 1)}</span><div><button disabled={!offset} aria-label="Предыдущая страница" onClick={() => setOffset(Math.max(0, offset - 30))}><ChevronLeft size={18}/></button><button disabled={offset + 30 >= data.total} aria-label="Следующая страница" onClick={() => setOffset(offset + 30)}><ChevronRight size={18}/></button></div></div>
    </> : <div className="returns-empty"><Clock3 size={24}/><strong>Возвраты пока не найдены</strong><span>Записи появятся после проверки сохранённых данных маркетплейса. Открытие страницы не запускает полную синхронизацию.</span></div>}
  </section>;
}
