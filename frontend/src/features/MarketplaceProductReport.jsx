import { useEffect, useMemo, useState } from "react";
import { Download, Save } from "lucide-react";
import { api, downloadApiFile } from "../services/api";
import { money } from "../utils/formatters";
import { can } from "../utils/permissions";
import { Empty, ErrorBox, Spinner } from "../components/Feedback";

const moneyCell = (value) => value == null ? "—" : money(value);
const keyOf = (row) => `${row.company_id}:${row.product_id}`;

export default function MarketplaceProductReport({ ctx }) {
  const [channel, setChannel] = useState("");
  const [accountId, setAccountId] = useState("");
  const [data, setData] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState({});
  const [downloading, setDownloading] = useState(false);
  const writable = can(ctx.auth, "finance", true);

  const accounts = (ctx.refs.accounts || []).filter((account) =>
    account.active !== false &&
    ["Kaspi", "Wildberries", "Ozon"].includes(account.channel) &&
    (!channel || account.channel === channel) &&
    (!ctx.company || String(account.company_id) === String(ctx.company))
  );

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
  const totals = items.reduce((sum, row) => ({
    sold: sum.sold + Number(row.sold_units || 0),
    returned: sum.returned + Number(row.returned_units || 0),
    revenue: sum.revenue + Number(row.net_revenue || 0),
    cost: sum.cost + (row.cogs == null ? 0 : Number(row.cogs)),
    tax: sum.tax + (row.tax == null ? 0 : Number(row.tax)),
    commission: sum.commission + Number(row.commission || 0),
    logistics: sum.logistics + Number(row.logistics || 0),
    profit: sum.profit + (row.profit == null ? 0 : Number(row.profit)),
    incomplete: sum.incomplete || row.profit == null,
  }), { sold: 0, returned: 0, revenue: 0, cost: 0, tax: 0, commission: 0, logistics: 0, profit: 0, incomplete: false });

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
      <style>{`
        .product-market-report{padding:20px}
        .pmr-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:16px}
        .pmr-head h2{margin:0 0 4px}.pmr-head p,.pmr-note{color:#74847b;font-size:12px;margin:0}
        .pmr-controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:14px 0}
        .pmr-controls select{min-height:38px;border:1px solid #dce6df;border-radius:8px;background:#fff;padding:0 12px;color:#29483b}
        .pmr-scroll{overflow:auto;border:1px solid #d5dfec;border-radius:8px}
        .pmr-table{width:100%;border-collapse:collapse;min-width:900px;table-layout:fixed;font-size:11px}
        .pmr-table th{background:#2863b4;color:#fff;text-align:left;font-weight:700;padding:9px 7px;white-space:normal;line-height:1.2;border:1px solid #1d559e}
        .pmr-table th:nth-child(1){width:20%}.pmr-table th:nth-child(2){width:10%}.pmr-table th:nth-child(3){width:10%}.pmr-table th:nth-child(4){width:12%}.pmr-table th:nth-child(5){width:14%}.pmr-table th:nth-child(6){width:13%}.pmr-table th:nth-child(7){width:12%}.pmr-table th:nth-child(8){width:9%}
        .pmr-table td{border:1px solid #dce4ee;padding:8px 7px;vertical-align:middle;overflow-wrap:anywhere}
        .pmr-table tbody tr:nth-child(even){background:#f7f9fc}
        .pmr-product-name{font-weight:650;color:#233f33;line-height:1.3}
        .pmr-product-meta,.pmr-table small{display:block;color:#718093;font-size:10px;line-height:1.3;margin-top:3px}
        .pmr-cell-stack{display:grid;gap:4px}
        .pmr-edit-inline{display:flex;align-items:center;gap:4px}
        .pmr-edit-inline input{width:72px;max-width:100%;border:1px solid #d4dfeb;border-radius:5px;padding:5px 6px;font-size:11px}
        .pmr-row-save{width:100%;justify-content:center!important;padding:5px!important;font-size:10px!important;margin-top:2px}
        .pmr-actions{display:flex;gap:6px;justify-content:flex-end}
        .pmr-summary{display:grid;grid-template-columns:repeat(5,minmax(100px,1fr));gap:10px;margin:14px 0}
        .pmr-stat{border:1px solid #e8eee9;border-radius:9px;padding:12px;background:#fbfcfb}
        .pmr-stat small{display:block;color:#78877e;font-size:11px}.pmr-stat strong{display:block;margin-top:4px;font-size:15px}
        .pmr-mobile{display:none}
        @media(max-width:760px){
          .product-market-report{padding:14px}
          .pmr-head{align-items:flex-start;flex-direction:column}
          .pmr-head button{width:100%}
          .pmr-controls{display:grid;grid-template-columns:1fr}
          .pmr-controls select{width:100%}
          .pmr-summary{grid-template-columns:repeat(2,minmax(0,1fr))}
          .pmr-scroll{display:none}
          .pmr-mobile{display:grid;gap:10px}
          .pmr-card{border:1px solid #e5ebe7;border-radius:10px;padding:13px;background:#fff}
          .pmr-card-title{display:flex;justify-content:space-between;gap:8px;margin-bottom:3px}
          .pmr-card-title strong{font-size:14px}
          .pmr-meta{font-size:11px;color:#75847b;margin-bottom:10px}
          .pmr-card-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
          .pmr-card-grid span{display:block;font-size:10px;color:#7a8980}
          .pmr-card-grid b{display:block;font-size:12px;font-weight:650;overflow-wrap:anywhere}
          .pmr-edit{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:11px}
          .pmr-edit label{font-size:10px;color:#75847b}
          .pmr-edit input{display:block;width:100%;margin-top:3px;border:1px solid #dce6df;border-radius:6px;padding:8px}
          .pmr-actions{margin-top:10px}
        }
      `}</style>
      <div className="pmr-head">
        <div>
          <h2>Отчёт по товарам маркетплейсов</h2>
          <p>Продажи и возвраты из синхронизированных данных за выбранный период.</p>
        </div>
        <button className="secondary" type="button" disabled={downloading || !items.length} onClick={exportExcel}>
          <Download size={16}/>{downloading ? "Готовим Excel…" : "Скачать готовый Excel"}
        </button>
      </div>
      <div className="pmr-controls">
        <select aria-label="Маркетплейс" value={channel} onChange={(e) => { setChannel(e.target.value); setAccountId(""); }}>
          <option value="">Все маркетплейсы</option>
          <option value="Kaspi">Kaspi</option><option value="Wildberries">Wildberries</option><option value="Ozon">Ozon</option>
        </select>
        <select aria-label="Магазин" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Все магазины</option>
          {accounts.map((account) => <option key={account.id} value={account.id}>{account.channel} · {account.name}</option>)}
        </select>
        <span className="pmr-note">Период: {ctx.start} — {ctx.end}. Налог указан ставкой для товара и считается от чистой выручки.</span>
      </div>
      <ErrorBox error={error}/>
      <div className="pmr-summary">
        <div className="pmr-stat"><small>Продано</small><strong>{totals.sold}</strong></div>
        <div className="pmr-stat"><small>Возвращено</small><strong>{totals.returned}</strong></div>
        <div className="pmr-stat"><small>Чистая выручка</small><strong>{moneyCell(totals.revenue)}</strong></div>
        <div className="pmr-stat"><small>Налог</small><strong>{totals.incomplete ? "Заполните ставку" : moneyCell(totals.tax)}</strong></div>
        <div className="pmr-stat"><small>Прибыль после расходов</small><strong>{totals.incomplete ? "Заполните налог и себестоимость" : moneyCell(totals.profit)}</strong></div>
      </div>
      {loading ? <Spinner/> : items.length === 0 ? <Empty/> : <>
        <div className="pmr-scroll">
          <table className="pmr-table">
            <thead><tr>
              <th>Артикул / SKU и товар</th><th>Площадка / магазин</th><th>Продано / возврат</th>
              <th>Чистая выручка</th><th>Себестоимость</th><th>Налог</th>
              <th>Комиссия / логистика / реклама</th><th>Прибыль</th>
            </tr></thead>
            <tbody>{items.map((row) => {
              const key = keyOf(row), draft = drafts[key] || {};
              return <tr key={`${key}:${row.account_id}`}>
                <td>
                  <div className="pmr-product-name">{row.product_name}</div>
                  <div className="pmr-product-meta">{row.article || row.sku}{row.article && row.sku && row.article !== row.sku ? ` · ${row.sku}` : ""}</div>
                </td>
                <td>{row.channel}<small>{row.account_name}</small></td>
                <td><strong>{row.sold_units} / {row.returned_units}</strong><small>шт. продано / возврат</small></td>
                <td>{moneyCell(row.net_revenue)}</td>
                <td><div className="pmr-cell-stack">
                  <label className="pmr-edit-inline"><span>За шт.</span><input aria-label={`Себестоимость ${row.product_name}`} type="number" min="0" step="0.01" value={draft.unitCost ?? ""} disabled={!writable} onChange={(e) => edit(row,"unitCost",e.target.value)}/></label>
                  <small>Итого: {moneyCell(row.cogs)}</small>
                </div></td>
                <td><div className="pmr-cell-stack">
                  <label className="pmr-edit-inline"><input aria-label={`Налог, процент ${row.product_name}`} type="number" min="0" max="100" step="0.01" value={draft.taxRate ?? ""} disabled={!writable} onChange={(e) => edit(row,"taxRate",e.target.value)}/><span>%</span></label>
                  <small>Итого: {moneyCell(row.tax)}</small>
                  {writable && <button className="secondary pmr-row-save" type="button" disabled={saving[key]} onClick={() => save(row)}><Save size={12}/>{saving[key] ? "Сохраняем…" : "Сохранить"}</button>}
                </div></td>
                <td><div className="pmr-cell-stack">
                  <span>Ком.: {moneyCell(row.commission)}</span>
                  <span>Лог.: {moneyCell(row.logistics)}</span>
                  <span>Реклама: {moneyCell(row.advertising)}</span>
                </div></td>
                <td><strong>{moneyCell(row.profit)}</strong></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <div className="pmr-mobile">{items.map((row) => {
          const key = keyOf(row), draft = drafts[key] || {};
          return <article className="pmr-card" key={`${key}:${row.account_id}`}>
            <div className="pmr-card-title"><strong>{row.product_name}</strong><b>{row.sku}</b></div>
            <div className="pmr-meta">{row.article || "Артикул не указан"} · {row.channel} · {row.account_name}</div>
            <div className="pmr-card-grid">
              <div><span>Продано / возврат</span><b>{row.sold_units} / {row.returned_units} шт.</b></div>
              <div><span>Чистая выручка</span><b>{moneyCell(row.net_revenue)}</b></div>
              <div><span>Себестоимость</span><b>{moneyCell(row.cogs)}</b></div>
              <div><span>Налог</span><b>{row.tax_rate_percent == null ? "Не задан" : `${row.tax_rate_percent}% · ${moneyCell(row.tax)}`}</b></div>
              <div><span>Комиссия</span><b>{moneyCell(row.commission)}</b></div>
              <div><span>Логистика</span><b>{moneyCell(row.logistics)}</b></div>
              <div><span>Прибыль</span><b>{moneyCell(row.profit)}</b></div>
            </div>
            {writable && <div className="pmr-edit">
              <label>Себестоимость за шт., ₸<input type="number" min="0" step="0.01" value={draft.unitCost ?? ""} onChange={(e) => edit(row,"unitCost",e.target.value)}/></label>
              <label>Налог, %<input type="number" min="0" max="100" step="0.01" value={draft.taxRate ?? ""} onChange={(e) => edit(row,"taxRate",e.target.value)}/></label>
            </div>}
            {writable && <div className="pmr-actions"><button className="secondary" type="button" disabled={saving[key]} onClick={() => save(row)}><Save size={14}/>{saving[key] ? "Сохраняем…" : "Сохранить"}</button></div>}
          </article>;
        })}</div>
      </>}
    </section>
  );
}
