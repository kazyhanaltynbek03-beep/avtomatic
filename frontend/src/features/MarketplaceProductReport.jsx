import { useEffect, useMemo, useState } from "react";
import { Download, Save, FileSpreadsheet, CalendarDays, Package, Warehouse, RotateCcw, Wallet, Percent, TrendingUp, ChevronDown } from "lucide-react";
import { api, downloadApiFile } from "../services/api";
import { money } from "../utils/formatters";
import { can } from "../utils/permissions";
import { Empty, ErrorBox, Spinner } from "../components/Feedback";

const moneyCell = (value) => value == null ? "—" : money(value);
const keyOf = (row) => `${row.company_id}:${row.product_id}`;
const marketplaceParts = (value) => String(value || "").split(/\s*[,;]\s*/).filter(Boolean).map((label) => {
  const lower = label.toLowerCase();
  const channel = /wildberries|\bwb\b|вайлдберриз/.test(lower) ? "Wildberries" : /ozon|озон/.test(lower) ? "Ozon" : /kaspi|каспи/.test(lower) ? "Kaspi" : "Маркетплейс";
  const store = label.includes("·") ? label.split("·").slice(1).join("·").trim() : "";
  return { channel, store, label };
});

function MarketplaceBadges({ names, count }) {
  const parts = marketplaceParts(names);
  if (!parts.length) return <span className="pmr-marketplace-empty">{count ? `${count} карточек · площадка не указана` : "Карточки не привязаны"}</span>;
  return <div className="pmr-marketplace-badges">{parts.map((part, index) => <span className={`pmr-marketplace-badge pmr-marketplace-badge--${part.channel.toLowerCase()}`} key={`${part.label}-${index}`} title={part.label}>
    <b aria-hidden="true">{part.channel === "Wildberries" ? "WB" : part.channel === "Kaspi" ? "K" : "O"}</b><span>{part.store || part.channel}</span>
  </span>)}</div>;
}

export default function MarketplaceProductReport({ ctx }) {
  const [channel, setChannel] = useState(ctx.marketplaceReportChannel || "");
  const [accountId, setAccountId] = useState("");
  const [data, setData] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState({});
  const [downloading, setDownloading] = useState(false);\n  const [tab, setTab] = useState("summary");
  const writable = can(ctx.auth, "finance", true);

  const accounts = (ctx.refs.accounts || []).filter((account) =>
    account.active !== false &&
    ["Kaspi", "Wildberries", "Ozon"].includes(account.channel) &&
    (!channel || account.channel === channel) &&
    (!ctx.company || String(account.company_id) === String(ctx.company))
  );

  useEffect(() => { setChannel(ctx.marketplaceReportChannel || ""); setAccountId(""); }, [ctx.marketplaceReportChannel]);

  const params = useMemo(() => {
    const query = new URLSearchParams({ start: ctx.start, end: ctx.end });
    if (ctx.company) query.set("company_id", ctx.company);
    if (channel) query.set("channel", channel);
    if (accountId) query.set("account_id", accountId);
    return query;
  }, [ctx.start, ctx.end, ctx.company, channel, accountId]);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    api("/marketplace-product-report?" + params.toString())
      .then((result) => {
        if (!current) return;
        setData(result);
        setDrafts((old) => {
          const next = { ...old };
          for (const row of result.items || []) {
            const key = keyOf(row);
            if (!next[key]) next[key] = {
              unitCost: row.unit_cost_tenge == null ? "" : String(row.unit_cost_tenge),
              taxRate: row.tax_rate_percent == null ? "" : String(row.tax_rate_percent),
            };
            else {
              next[key] = {
                unitCost: row.unit_cost_tenge == null ? "" : String(row.unit_cost_tenge),
                taxRate: row.tax_rate_percent == null ? "" : String(row.tax_rate_percent),
              };
            }
          }
          return next;
        });
      })
      .catch((e) => { if (current) setError(e.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [params, ctx.refresh]);

  const items = data?.items || [];
  const incompleteItems = items.filter((row) => row.profit == null).length;
  const totals = items.reduce((sum, row) => ({
    sold: sum.sold + Number(row.sold_units || 0),
    stock: sum.stock + Number(row.available_stock || 0),
    returned: sum.returned + Number(row.returned_units || 0),
    revenue: sum.revenue + Number(row.net_revenue || 0),
    cost: sum.cost + (row.cogs == null ? 0 : Number(row.cogs)),
    tax: sum.tax + (row.tax == null ? 0 : Number(row.tax)),
    commission: sum.commission + Number(row.commission || 0),
    logistics: sum.logistics + Number(row.logistics || 0),
    profit: sum.profit + (row.profit == null ? 0 : Number(row.profit)),
    incomplete: sum.incomplete || row.profit == null,
  }), { sold: 0, stock: 0, returned: 0, revenue: 0, cost: 0, tax: 0, commission: 0, logistics: 0, profit: 0, incomplete: false });

  const edit = (row, field, value) => {
    const key = keyOf(row);
    setDrafts((old) => ({ ...old, [key]: { ...(old[key] || {}), [field]: value } }));
  };
  const save = async (row) => {
    const key = keyOf(row);
    const draft = drafts[key] || {};
    const parseOptional = (value) => value === "" || value == null ? null : Number(value);
    const unitCost = parseOptional(draft.unitCost);
    const taxRate = parseOptional(draft.taxRate);
    if ((unitCost != null && (!Number.isFinite(unitCost) || unitCost < 0)) ||
        (taxRate != null && (!Number.isFinite(taxRate) || taxRate < 0 || taxRate > 100))) {
      setError("Себестоимость должна быть неотрицательной, налог — от 0 до 100%.");
      return;
    }
    setSaving((old) => ({ ...old, [key]: true }));
    setError("");
    try {
      await api("/marketplace-product-report/settings", {
        method: "PUT",
        body: {
          company_id: row.company_id,
          product_id: row.product_id,
          unit_cost_tenge: unitCost,
          tax_rate_percent: taxRate,
        },
      });
      ctx.notify("Себестоимость и налог сохранены");
      ctx.reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving((old) => ({ ...old, [key]: false }));
    }
  };
  const exportExcel = async () => {
    setDownloading(true);
    setError("");
    try {
      await downloadApiFile("/marketplace-product-report.xlsx?" + params.toString(), "Отчет-по-товарам-маркетплейсов.xlsx");
    } catch (e) {
      setError(e.message);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <section className="panel product-market-report">
      <div className="pmr-head">
        <div>
          <span className="pmr-eyebrow"><FileSpreadsheet size={14}/> ОТЧЁТ ПО ОБЪЕДИНЁННЫМ ТОВАРАМ</span>
          <h2>Продажи по внутренним SKU</h2>
          <p>Один товар — общие продажи связанных карточек и магазинов.</p>
        </div>
        <button className="primary pmr-export" type="button" disabled={downloading || !items.length} onClick={exportExcel}>
          <Download size={16}/>{downloading ? "Готовим Excel…" : "Скачать сводный Excel"}
        </button>
      </div>
      <div className="pmr-report-tabs">{[["summary","Жиынтық"],["settings","Баптаулар"],["stores","Тапсырыстар"],["weeks","Есеп аптасы"]].map(([id,label]) => <button type="button" key={id} className={tab === id ? "selected" : ""} onClick={() => setTab(id)}>{label}</button>)}</div>\n      <div className="pmr-controls">
        <select aria-label="Маркетплейс" value={channel} onChange={(e) => { setChannel(e.target.value); setAccountId(""); }}>
          <option value="">Все маркетплейсы</option>
          <option value="Kaspi">Kaspi</option><option value="Wildberries">Wildberries</option><option value="Ozon">Ozon</option>
        </select>
        <select aria-label="Магазин" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Все магазины</option>
          {accounts.map((account) => <option key={account.id} value={account.id}>{account.channel} · {account.name}</option>)}
        </select>
        <span className="pmr-note"><CalendarDays size={14}/> {ctx.start} — {ctx.end}<span>·</span> Комиссия, логистика и реклама показываются по сохранённым операциям.</span>
      </div>
      {incompleteItems > 0 && <div className="pmr-data-hint" role="status"><span>!</span><div><strong>Для {incompleteItems} товаров не хватает данных для расчёта прибыли</strong><small>Заполните себестоимость и ставку налога в строке товара, затем сохраните.</small></div></div>}
      <ErrorBox error={error}/>
      {tab === "summary" && <div className="pmr-summary">
        <div className="pmr-stat"><span className="pmr-stat-icon is-sold"><Package size={16}/></span><div><small>Продано</small><strong>{totals.sold} шт.</strong></div></div>
        <div className="pmr-stat"><span className="pmr-stat-icon is-stock"><Warehouse size={16}/></span><div><small>Общий остаток</small><strong>{totals.stock} шт.</strong></div></div>
        <div className="pmr-stat"><span className="pmr-stat-icon is-return"><RotateCcw size={16}/></span><div><small>Возвращено</small><strong>{totals.returned} шт.</strong></div></div>
        <div className="pmr-stat"><span className="pmr-stat-icon is-revenue"><Wallet size={16}/></span><div><small>Чистая выручка</small><strong>{moneyCell(totals.revenue)}</strong></div></div>
        <div className="pmr-stat"><span className="pmr-stat-icon is-tax"><Percent size={16}/></span><div><small>Налог</small><strong>{totals.incomplete ? "Не полностью" : moneyCell(totals.tax)}</strong></div></div>
        <div className="pmr-stat"><span className="pmr-stat-icon is-profit"><TrendingUp size={16}/></span><div><small>Прибыль после расходов</small><strong>{totals.incomplete ? "Нужны данные" : moneyCell(totals.profit)}</strong></div></div>
      </div>
      {loading ? <Spinner/> : items.length === 0 ? <Empty/> : <>
        <div className="pmr-scroll">
          <table className="pmr-table">
            <colgroup><col/><col/><col/><col/><col/><col/><col/><col/></colgroup>
            <thead><tr>
              <th>Товар / площадки</th><th>Цена / остаток</th><th>Продано / возврат</th><th>Чистая выручка</th>
              <th>Себестоимость</th><th>Налог</th><th>Расходы площадки</th><th>Прибыль</th>
            </tr></thead>
            <tbody>{items.map((row) => {
              const key = keyOf(row), draft = drafts[key] || {};
              return <tr key={`${key}:${row.account_id}`}>
                <td>
                  <div className="pmr-product-name">{row.product_name}</div>
                  <div className="pmr-product-meta">{row.article || row.sku}{row.article && row.sku && row.article !== row.sku ? ` · ${row.sku}` : ""}</div>
                  <MarketplaceBadges names={row.marketplace_names} count={row.marketplace_card_count}/>
                </td>
                <td><div className="pmr-cell-stack"><span><small>Цена продажи</small><b>{row.selling_price_tenge == null || Number(row.selling_price_tenge) === 0 ? "Не указана" : moneyCell(row.selling_price_tenge)}</b></span><span><small>На едином складе</small><b>{row.available_stock ?? 0} шт.</b></span></div></td>
                <td><strong>{row.sold_units} шт.</strong><small>Возврат: {row.returned_units} шт.</small></td>
                <td><strong className="pmr-money">{moneyCell(row.net_revenue)}</strong></td>
                <td><div className="pmr-cell-stack">
                  {writable && <label className="pmr-edit-inline"><span>За шт.</span><input aria-label={`Себестоимость ${row.product_name}`} type="number" min="0" step="0.01" value={draft.unitCost ?? ""} disabled={!writable} onChange={(e) => edit(row,"unitCost",e.target.value)}/></label>}
                  {!writable && <span><small>За шт.</small><b>{draft.unitCost ? money(draft.unitCost) : "Не задана"}</b></span>}
                  <small>Всего: {moneyCell(row.cogs)}</small>
                </div></td>
                <td><div className="pmr-cell-stack">
                  {writable && <label className="pmr-edit-inline"><input aria-label={`Налог, процент ${row.product_name}`} type="number" min="0" max="100" step="0.01" value={draft.taxRate ?? ""} disabled={!writable} onChange={(e) => edit(row,"taxRate",e.target.value)}/><span>%</span></label>}
                  {!writable && <span><small>Ставка</small><b>{draft.taxRate ? `${draft.taxRate}%` : "Не задана"}</b></span>}
                  <small>Всего: {moneyCell(row.tax)}</small>
                  {writable && <button className="secondary pmr-row-save" type="button" disabled={saving[key]} onClick={() => save(row)}><Save size={12}/>{saving[key] ? "Сохраняем…" : "Сохранить"}</button>}
                </div></td>
                <td><div className="pmr-cell-stack">
                  <span>Комиссия: {moneyCell(row.commission)}</span>
                  <span>Логистика: {moneyCell(row.logistics)}</span>
                  <span>Реклама: {moneyCell(row.advertising)}</span>
                </div></td>
                <td><strong className={row.profit == null ? "pmr-profit-missing" : "pmr-profit-value"}>{moneyCell(row.profit)}</strong></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <div className="pmr-mobile">{items.map((row) => {
          const key = keyOf(row), draft = drafts[key] || {};
          return <article className="pmr-card" key={`${key}:${row.account_id}`}>
            <div className="pmr-card-top"><div className="pmr-card-title"><strong>{row.product_name}</strong><small>SKU · {row.sku || row.article || "не указан"}</small></div><b className="pmr-card-profit">{moneyCell(row.profit)}</b></div>
            <MarketplaceBadges names={row.marketplace_names} count={row.marketplace_card_count}/>
            <div className="pmr-card-grid">
              <div><span>Продано</span><b>{row.sold_units} шт.</b></div>
              <div><span>Возврат</span><b>{row.returned_units} шт.</b></div>
              <div><span>Остаток</span><b>{row.available_stock ?? 0} шт.</b></div>
              <div><span>Чистая выручка</span><b>{moneyCell(row.net_revenue)}</b></div>
            </div>
            <details className="pmr-card-details">
              <summary>Цена, себестоимость и расходы <ChevronDown size={16}/></summary>
              <div className="pmr-detail-grid">
                <div><span>Цена продажи</span><b>{row.selling_price_tenge == null || Number(row.selling_price_tenge) === 0 ? "Не указана" : moneyCell(row.selling_price_tenge)}</b></div>
                <div><span>Себестоимость всего</span><b>{moneyCell(row.cogs)}</b></div>
                <div><span>Налог всего</span><b>{moneyCell(row.tax)}</b></div>
                <div><span>Комиссия</span><b>{moneyCell(row.commission)}</b></div>
                <div><span>Логистика</span><b>{moneyCell(row.logistics)}</b></div>
                <div><span>Реклама</span><b>{moneyCell(row.advertising)}</b></div>
              </div>
              {writable && <div className="pmr-edit">
                <label>Себестоимость за шт., ₸<input aria-label={`Себестоимость ${row.product_name}`} type="number" min="0" step="0.01" value={draft.unitCost ?? ""} onChange={(e) => edit(row,"unitCost",e.target.value)}/></label>
                <label>Налог, %<input aria-label={`Налог, процент ${row.product_name}`} type="number" min="0" max="100" step="0.01" value={draft.taxRate ?? ""} onChange={(e) => edit(row,"taxRate",e.target.value)}/></label>
                <button className="primary" type="button" disabled={saving[key]} onClick={() => save(row)}><Save size={14}/>{saving[key] ? "Сохраняем…" : "Сохранить изменения"}</button>
              </div>}
            </details>
          </article>;
        })}</div>
      </>}
    </section>
  );
}
