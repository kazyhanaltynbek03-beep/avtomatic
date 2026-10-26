Warning: truncated output (original token count: 54118)
Total output lines: 3594

import { useState, useEffect, useRef, useCallback, lazy, Suspense } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  Search,
  Plus,
  Menu,
  X,
  LogOut,
  Bell,
  Sparkles,
  Download,
  Upload,
  CheckCircle2,
  Trash2,
  Pencil,
  RotateCcw,
  FileText,
  RefreshCw,
  Send,
  Package,
  Wallet,
  TrendingUp,
  Layers,
  ShieldCheck,
  Paperclip,
  Copy,
  MessageSquare,
  Image as ImageIcon,
  Receipt,
} from "lucide-react";
import { api, setCsrf, downloadApiFile } from "../services/api";
import { money, decimal, today } from "../utils/formatters";
import { can } from "../utils/permissions";
import { ErrorBox, Empty, Spinner } from "../components/Feedback";
import { useLoad } from "../hooks/useLoad";
import { groups, forms, columns, labels, monetary } from "../config";
import "../style.css";
const flat = groups.flatMap((g) => g[1]);
const channels = ["Kaspi", "Wildberries", "Ozon", "Offline", "B2B"];
const KaspiPreorder = lazy(() => import("../features/KaspiPreorder"));
const AI_JOB_TIMEOUT_MS = 15 * 60 * 1000;
async function waitForAIJob(id, onUpdate = () => {}) {
  const deadline = Date.now() + AI_JOB_TIMEOUT_MS;
  let current = null;
  while (Date.now() < deadline) {
    current = await api("/jobs/" + id);
    onUpdate(current);
    if (!["queued", "running"].includes(current.status)) return current;
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }
  throw new Error("AI-задача #" + id + " всё ещё выполняется. Откройте страницу снова и проверьте статус позже.");
}
function Login({ onAuth }) {
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const submitLock = useRef(false);
  const submit = async (e) => {
    e.preventDefault();
    if (submitLock.current) return;
    submitLock.current = true;
    setBusy(true);
    setError("");
    try {
      const a = await api("/auth/login", {
        method: "POST",
        body: { email, password },
      });
      setCsrf(a.csrf);
      onAuth(a);
    } catch (e) {
      setError(e.message);
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  };
  return (
    <div className="login">
      <div className="login-story">
        <div className="brand">
          <span className="brand-mark">q</span>qor
          <span className="brand-dot">.</span>
        </div>
        <span className="eyebrow">BUSINESS WORKSPACE</span>
        <h1>
          Бизнес целиком.
          <br />
          Решения по цифрам.
        </h1>
        <p>
          Продажи, склад, финансы и AI —<br />в одном рабочем пространстве.
        </p>
        <div className="login-lines">
          <span>01 / Единый учёт</span>
          <span>02 / Прозрачная прибыль</span>
          <span>03 / Данные под контролем</span>
        </div>
      </div>
      <form className="login-form" onSubmit={submit}>
        <span className="pill">QOR BUSINESS</span>
        <h2>Добро пожаловать</h2>
        <p className="muted">Войдите в рабочее пространство компании</p>
        <label>
          Email
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="owner@company.kz"
          />
        </label>
        <label>
          Пароль
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <ErrorBox error={error} />
        <button className="primary" disabled={busy}>
          {busy ? "Входим…" : "Войти в систему"}
        </button>
        <small>
          <ShieldCheck size={15} /> Защищённая сессия · Доступ по ролям
        </small>
      </form>
    </div>
  );
}
export default function App() {
  const [auth, setAuth] = useState(undefined),
    [page, setPage] = useState(location.hash.slice(1) || "dashboard"),
    [mobile, setMobile] = useState(false),
    [refresh, setRefresh] = useState(0),
    [notice, setNotice] = useState(""),
    [refs, setRefs] = useState({}),
    [company, setCompany] = useState(""),
    [range, setRange] = useState("Месяц"),
    [start, setStart] = useState(today().slice(0, 8) + "01"),
    [end, setEnd] = useState(today()),
    [modal, setModal] = useState(null),
    [settings, setSettings] = useState({});
  const noticeTimer = useRef(null);
  useEffect(() => () => {
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
  }, []);
  useEffect(() => {
    api("/auth/me")
      .then((a) => {
        setCsrf(a.csrf);
        setAuth(a);
      })
      .catch(() => setAuth(null));
  }, []);
  const notify = (m) => {
    setNotice(m);
    setRefresh((v) => v + 1);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => {
      setNotice("");
      noticeTimer.current = null;
    }, 5000);
  };
  useEffect(() => {
    if (!auth) return;
    let live = true;
    Promise.all(
      [
        "companies",
        "products",
        "accounts",
      ].map(async (k) => {
        try {
          const items = (await api("/data/" + k + "?limit=500")).items;
          return [k, k === "accounts" ? items.filter((x) => x.active !== false) : items];
        } catch {
          return [k, []];
        }
      }),
    ).then((r) => {
      if (live) setRefs(Object.fromEntries(r));
    });
    api("/settings")
      .then(setSettings)
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [auth, refresh]);
  const navigate = (id) => {
    setPage(id);
    location.hash = id;
    setMobile(false);
  };
  useEffect(() => {
    const fn = () => setPage(location.hash.slice(1) || "dashboard");
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  useEffect(() => {
    if (!auth) return;
    const item = flat.find((x) => x[0] === page);
    if (!item || !can(auth, item[3]))
      navigate(flat.find((x) => can(auth, x[3]))?.[0] || "settings");
  }, [auth, page]);
  const chooseRange = (v) => {
    setRange(v);
    const now = new Date(today() + "T12:00:00Z");
    let a = new Date(now),
      b = new Date(now);
    const mondayOffset = (now.getUTCDay() + 6) % 7;
    if (v === "Вчера") {
      a.setUTCDate(a.getUTCDate() - 1);
      b = new Date(a);
    }
    if (v === "Неделя") a.setUTCDate(a.getUTCDate() - mondayOffset);
    if (v === "Прошлая неделя") {
      a.setUTCDate(a.getUTCDate() - mondayOffset - 7);
      b.setUTCDate(b.getUTCDate() - mondayOffset - 1);
    }
    if (v === "Месяц") a.setUTCDate(1);
    if (v === "Прошлый месяц") {
      a.setUTCDate(1);
      a.setUTCMonth(a.getUTCMonth() - 1);
      b = new Date(a);
      b.setUTCMonth(b.getUTCMonth() + 1);
      b.setUTCDate(0);
    }
    if (v === "Квартал") a.setUTCMonth(Math.floor(a.getUTCMonth() / 3) * 3, 1);
    if (v === "Год") a.setUTCMonth(0, 1);
    if (v === "Прошлый год") {
      a.setUTCMonth(0, 1);
      a.setUTCFullYear(a.getUTCFullYear() - 1);
      b = new Date(a);
      b.setUTCFullYear(b.getUTCFullYear() + 1);
      b.setUTCDate(0);
    }
    if (v !== "Период") {
      setStart(a.toISOString().slice(0, 10));
      setEnd(b.toISOString().slice(0, 10));
    }
  };
  if (auth === undefined) return <Spinner />;
  if (!auth) return <Login onAuth={setAuth} />;
  const current = flat.find((x) => x[0] === page) || flat[0];
  const ctx = {
    auth,
    refs,
    company,
    start,
    end,
    refresh,
    notify,
    navigate,
    open: (kind, item) => setModal({ kind, item }),
  };
  const logout = async () => {
    await api("/auth/logout", { method: "POST" });
    setAuth(null);
    setCsrf("");
  };
  return (
    <div className="app">
      <div
        className={"scrim " + (mobile ? "show" : "")}
        onClick={() => setMobile(false)}
      />
      <aside className={mobile ? "open" : ""} aria-label="Главное меню">
        <button className="sidebar-close" onClick={() => setMobile(false)} aria-label="Закрыть меню"><X size={20} /></button>
        <a
          href="#dashboard"
          className="brand"
          onClick={() => navigate("dashboard")}
        >
          <span className="brand-mark">q</span>qor
          <span className="brand-dot">.</span>
          <span className="workspace-tag">BUSINESS</span>
        </a>
        <div className="workspace">
          <div className="workspace-avatar">GK</div>
          <div>
            <strong>{settings.business_name || "QOR Business"}</strong>
            <small>Рабочее пространство</small>
          </div>
        </div>
        <nav>
          {groups.map(([title, items]) => {
            const filtered = items.filter((x) => can(auth, x[3]));
            return (
              filtered.length > 0 && (
                <section key={title}>
                  <h4>{title}</h4>
                  {filtered.map(([id, name, I]) => (
                    <button
                      key={id}
                      className={page === id ? "nav-item active" : "nav-item"}
                      aria-current={page === id ? "page" : undefined}
                      onClick={() => navigate(id)}
                    >
                      <I size={18} />
                      <span>{name}</span>
                      {id === "assistant" && <i>AI</i>}
                    </button>
                  ))}
                </section>
              )
            );
          })}
        </nav>
        <div className="profile">
          <div className="avatar">{auth.user.name[0]}</div>
          <div>
            <strong>{auth.user.name}</strong>
            <small>{auth.user.role}</small>
          </div>
          <button className="icon-button" onClick={logout} title="Выйти">
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header>
          <button
            className="icon-button mobile-menu"
            onClick={() => setMobile(true)}
            aria-label="Открыть меню"
          >
            <Menu />
          </button>
          <div className="breadcrumb">
            Рабочее пространство <span>/</span> <strong>{current[1]}</strong>
          </div>
          <div className="header-right">
            {settings.demo && <span className="demo-badge">ДЕМО-ДАННЫЕ</span>}
            <span className="currency">KZT · ₸</span>
            {can(auth, "analytics") && (
              <button
                className="icon-button"
                onClick={() => navigate("alerts")}
                aria-label="Уведомления"
              >
                <Bell size={19} />
              </button>
            )}
            <div className="avatar small">{auth.user.name[0]}</div>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {["assistant", "niches", "content", "designer"].includes(page)
                  ? "INTELLIGENCE"
                  : "BUSINESS OVERVIEW"}
              </div>
              <h1>{current[1]}</h1>
              <p>
                {page === "dashboard"
                  ? "Главные показатели и то, что требует вашего внимания."
                  : page === "stock"
                    ? "Один физический склад. Остатки разделены по владельцам."
                    : page === "accounts"
                      ? "Каналы продаж и отдельные аккаунты ваших компаний."
                      : "Данные рабочего пространства"}
              </p>
            </div>
            {[
              "dashboard",
              "sales",
              "purchases",
              "products",
              "expenses",
              "cash",
              "companies",
              "accounts",
              "customers",
              "users",
              "niches",
            ].includes(page) &&
              can(auth, page === "dashboard" ? "sales" : current[3], true) &&
              (!["companies", "users"].includes(page) ||
                auth.user.role === "Owner") && (
                <button
                  className="primary"
                  onClick={() =>
                    setModal({ kind: page === "dashboard" ? "sales" : page })
                  }
                >
                  <Plus size={18} />
                  {page === "dashboard" ? "Новая продажа" : "Добавить"}
                </button>
              )}
          </div>
          <div className="toolbar">
            <div className="filter-company">
              <BuildingSelect
                refs={refs}
                company={company}
                setCompany={setCompany}
              />
            </div>
            {[
              "dashboard",
              "analytics",
              "profit",
              "forecast",
              "alerts",
              "accounting",
              "expenses",
              "cash",
              ...channels.slice(0, 3),
            ].includes(page) && (
              <div className="periods">
                {[
                  "Сегодня",
                  "Вчера",
                  "Неделя",
                  "Прошлая неделя",
                  "Месяц",
                  "Прошлый месяц",
                  "Квартал",
                  "Год",
                  "Прошлый год",
                  "Период",
                ].map((v) => (
                  <button
                    className={v === range ? "selected" : ""}
                    key={v}
                    onClick={() => chooseRange(v)}
                  >
                    {v}
                  </button>
                ))}
              </div>
            )}
            <button
              className="icon-button refresh"
              title="Обновить"
              onClick={() => setRefresh((x) => x + 1)}
            >
              <RefreshCw size={17} />
            </button>
          </div>
          {range === "Период" &&
            [
              "dashboard",
              "analytics",
              "profit",
              "forecast",
              "alerts",
              "accounting",
              "expenses",
              "cash",
              ...channels.slice(0, 3),
            ].includes(page) && (
              <div className="dates">
                <label>
                  С
                  <input
                    type="date"
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                  />
                </label>
                <label>
                  По
                  <input
                    type="date"
                    value={end}
                    onChange={(e) => setEnd(e.target.value)}
                  />
                </label>
              </div>
            )}
          {[
            "dashboard",
            "analytics",
            "profit",
            "forecast",
            "alerts",
            "accounting",
          ].includes(page) ? (
            <ReportPage page={page} ctx={ctx} />
          ) : page === "stock" ? (
            <Stock ctx={ctx} />
          ) : ["assistant", "content", "designer"].includes(page) ? (
            <AIPage
              key={page}
              page={page}
              ctx={ctx}
              enabled={settings.ai_enabled}
            />
          ) : page === "calculator" ? (
            <Calculator />
          ) : page === "imports" ? (
            <Imports ctx={ctx} />
          ) : page === "kaspi-preorder" ? (
            <Suspense fallback={<Spinner />}><KaspiPreorder ctx={ctx} /></Suspense>
          ) : page === "roles" ? (
            <Roles />
          ) : page === "settings" ? (
            <Settings
              settings={settings}
              ctx={ctx}
              onLogout={() => setAuth(null)}
            />
          ) : page === "expenses" ? (
            <><ExpenseSummary ctx={ctx}/><DataPage key={page} page={page} ctx={ctx}/></>
          ) : (
            <DataPage key={page} page={page} ctx={ctx} />
          )}
          <footer>
            <span>QOR Business</span>
            <span>Asia/Almaty · Учёт в KZT</span>
          </footer>
        </main>
      </div>
      <nav className="mobile-dock" aria-label="Основная мобильная навигация">
        {[
          ["dashboard", "Обзор", TrendingUp],
          ["sales", "Продажи", Receipt],
          ["assistant", "QOR AI", Sparkles],
          ["stock", "Склад", Package],
        ].filter(([id]) => {
          const item = flat.find((x) => x[0] === id);
          return item && can(auth, item[3]);
        }).map(([id, label, DockIcon]) => (
          <button key={id} className={page === id ? "active" : ""} onClick={() => navigate(id)}>
            <DockIcon size={20} />
            <span>{label}</span>
          </button>
        ))}
        <button onClick={() => setMobile(true)} className={mobile ? "active" : ""}>
          <Menu size={20} />
          <span>Меню</span>
        </button>
      </nav>
      {notice && (
        <div className="toast" role="status">
          <CheckCircle2 size={19} />
          {notice}
        </div>
      )}
      {modal && (
        <EditModal
          kind={modal.kind}
          item={modal.item}
          ctx={ctx}
          close={() => setModal(null)}
        />
      )}
    </div>
  );
}
function BuildingSelect({ refs, company, setCompany }) {
  return (
    <select
      aria-label="Компания"
      value={company}
      onChange={(e) => setCompany(e.target.value)}
    >
      <option value="">Все доступные компании</option>
      {refs.companies?.map((x) => (
        <option key={x.id} value={x.id}>
          {x.name}
        </option>
      ))}
    </select>
  );
}
function Table({ rows, cols, refs = {}, actions, raw = false, entity = "" }) {
  const fmt = (row, k) => {
    const v = k === "score" ? row.analysis?.score : row[k];
    if (raw) return v == null ? "—" : String(v);
    if (v == null) return "—";
    if (entity === "expenses" && k === "category") {
      const categoryLabels = {
        "Marketplace commission": "Комиссия маркетплейса",
        "Marketplace commission VAT": "НДС с комиссии",
        "Marketplace acquiring": "Эквайринг",
        "Marketplace logistics": "Логистика",
        "Marketplace return logistics": "Обратная логистика",
        "Marketplace storage": "Хранение",
        "Marketplace acceptance": "Приёмка",
        "Marketplace penalties": "Штрафы",
        "Marketplace deductions": "Удержания",
        "Marketplace other expenses": "Прочие расходы маркетплейса",
        "Реклама": "Реклама",
      };
      return categoryLabels[v] || v;
    }
    if (entity === "expenses" && k === "reference") {
      const account = refs.accounts?.find((item) => item.id === row.account_id);
      const channel = {Kaspi:"Kaspi",Wildberries:"Wildberries",Ozon:"Ozon",Offline:"Офлайн",B2B:"B2B"}[account?.channel] || "Офлайн";
      const raw = String(v);
      const technical = /^(Kaspi|Wildberries|Ozon):expense:/i.test(raw);
      const humanReference = technical ? "автоимпорт" : raw;
      return <span title={raw}>{channel} · {account?.name || "расход"} · {humanReference}</span>;
    }
    if (monetary.has(k)) return money(v);
    if (k === "active")
      return (
        <span className={"badge " + (v ? "green" : "gray")}>
          {v ? "Активен" : "Отключён"}
        </span>
      );
    if (k === "mode")
      return (
        <span className={"badge " + (v === "api" ? "amber" : "gray")}>
          {v === "csv"
            ? "CSV / Excel"
            : v === "demo"
              ? "Demo adapter"
              : "API"}
        </span>
      );
    if (k === "score") return <span className="score">{v} / 100</span>;
    if (k === "overdue") return v ? "Да" : "Нет";
    const rel = {
      company_id: "companies",
      product_id: "products",
      account_id: "accounts",
      sale_id: "sales",
      customer_id: "customers",
      user_id: "users",
    }[k];
    if (rel)
      return (
        refs[rel]?.find((x) => x.id === v)?.name ||
        refs[rel]?.find((x) => x.id === v)?.reference ||
        "#" + v
      );
    if (k === "company_ids")
      return v.length
        ? v
            .map(
              (id) =>
                refs.companies?.find((c) => c.id === id)?.name || "#" + id,
            )
            .join(", ")
        : "—";
    if (k === "created_at" || k === "last_sync")
      return new Date(v).toLocaleString("ru-RU", { timeZone: "Asia/Almaty" });
    if (k === "size") return Math.ceil(v / 1024) + " КБ";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  };
  if (!rows.length) return <Empty />;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {cols.map((k) => (
              <th key={k}>{labels[k] || k}</th>
            ))}
            {actions && <th>Действия</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id || i}>
              {cols.map((k, j) => (
                <td key={k} data-label={labels[k] || k} className={j === 0 ? "strong" : ""}>
                  {fmt(row, k)}
                </td>
              ))}
              {actions && (
                <td data-label="Действия">
                  <div className="row-actions">{actions(row)}</div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function CostPendingNotice({ report, ctx }) {
  if (report.profit_complete !== false) return null;
  const pending = Number(report.pending_cogs_sales || 0);
  const channels = (report.channel_summary || []).filter(
    (channel) => Number(channel.pending_cogs || 0) > 0 &&
      ["Kaspi", "Wildberries", "Ozon"].includes(channel.channel),
  );
  return (
    <div className="panel cost-pending-banner" role="status">
      <div>
        <strong>{pending > 0 ? `Себестоимость не заполнена для ${pending} продаж` : "Есть подтверждённые операции, ожидающие обработки"}</strong>
        <p>{pending > 0 ? "Выручка и комиссия уже учтены. Валовая и чистая прибыль появятся после внесения закупочной себестоимости по продажам." : "Прибыль, маржа и ROI появятся после обработки ожидающих операций."}</p>
      </div>
      <div className="cost-pending-actions">
        {can(ctx.auth, "finance") ? channels.map((channel) => (
          <button key={channel.channel} className="secondary" type="button" onClick={() => ctx.navigate(channel.channel)}>
            Заполнить {channel.channel} · {channel.pending_cogs}
          </button>
        )) : pending > 0 ? <small>Изменение себестоимости доступно финансовой роли.</small> : null}
      </div>
    </div>
  );
}
function ExpenseSummary({ ctx }) {
  const params = new URLSearchParams({start:ctx.start, end:ctx.end});
  if (ctx.company) params.set("company_id", ctx.company);
  const {data, error, loading} = useLoad(`/expenses/summary?${params}`, ctx.refresh);
  if (loading) return <section className="panel expense-summary"><Spinner/></section>;
  if (error) return <section className="panel expense-summary"><ErrorBox error={error}/></section>;
  const summary = data || {};
  return <section className="panel expense-summary" aria-label="Расходы по источникам и категориям">
    <div className="panel-heading"><div><h2>Расходы за период</h2><p className="muted">{ctx.start} — {ctx.end} · маркетплейсы, офлайн и B2B</p></div></div>
    <div className="secondary-kpis compact-kpis">
      <div><span>Всего с расчётными комиссиями</span><strong>{money(summary.total || 0)}</strong></div>
      <div><span>Проведено в учёте</span><strong>{money(summary.posted_total || 0)}</strong></div>
      <div><span>Расчётная комиссия Kaspi</span><strong>{money(summary.commission_estimated || 0)}</strong></div>
      <div><span>Записей</span><strong>{summary.records || 0}</strong></div>
    </div>
    {summary.commission_estimate_warning && <p className="panel-note amber">Есть фактические комиссии Kaspi. Расчёт по ставке не добавлен, чтобы не задвоить расходы.</p>}
      <div className="expense-summary-grid">
      <div><h3>По маркетплейсам и каналам</h3><Table rows={summary.channels || []} cols={["channel_label","account_name","posted_total","estimated_total","total"]}/></div>
      <div><h3>По назначению</h3><Table rows={summary.categories || []} cols={["category","posted_total","estimated_total","total"]}/></div>
    </div>
    <p className="panel-note">Проведено — подтверждённые операции расходов и продаж. Расчётная комиссия показана отдельно и не является фактическим удержанием или выплатой.</p>
  </section>;
}
function ReportPage({ page, ctx }) {
  const [detailMetric, setDetailMetric] = useState(null);
  const usesDashboard = page === "dashboard" || page === "analytics";
  const reportPath = "/report?start=" + ctx.start + "&end=" + ctx.end +
    (ctx.company ? "&company_id=" + ctx.company : "");
  const summaryPath = "/dashboard/summary?start=" + ctx.start + "&end=" + ctx.end +
    (ctx.company ? "&company_id=" + ctx.company : "");
  const alertsPath = page === "alerts" ? "/alerts?start=" + ctx.start + "&end=" + ctx.end +
    (ctx.company ? "&company_id=" + ctx.company : "") : null;
  const { data: loadedReport, error: reportError, loading: reportLoading } = useLoad(
    page === "forecast" ? null : reportPath,
    ctx.refresh,
  );
  const { data: dash, error: dashError, loading: dashLoading } = useLoad(
    usesDashboard ? summaryPath : null,
    ctx.refresh,
  );
  const { data: systemAlerts, error: systemAlertsError } = useLoad(alertsPath, ctx.refresh);
  const r = usesDashboard ? (loadedReport || dash?.report) : loadedReport;
  if (usesDashboard && dashLoading) return <Spinner />;
  if (usesDashboard && dashError) return <ErrorBox error={dashError} />;
  if (usesDashboard && !loadedReport) {
    const fast = dash?.report || {};
    const headline = [
      ["Оборот сегодня", dash?.today?.revenue, "На " + (dash?.as_of || "")],
      ["Прибыль сегодня", dash?.today?.net_profit, "Чистая прибыль"],
      ["Оборот месяца", dash?.month?.revenue, "С начала месяца"],
      ["Валовая прибыль месяца", dash?.month?.gross_profit, "С начала месяца"],
      ["Чистая прибыль месяца", dash?.month?.net_profit, "С начала месяца"],
    ];
    const kpis = [
      ["Оборот", fast.revenue, "За вычетом возвратов"],
      ["Валовая прибыль", fast.gross_profit, "Выручка − себестоимость"],
      ["Чистая прибыль", fast.net_profit, "После учтённых расходов"],
      ["Маржинальность", fast.margin == null ? "—" : decimal(fast.margin) + "%", "Чистая прибыль / выручка"],
    ];
    return (
      <>
        <div className="dashboard-headline">
          {headline.map(([title, value, note]) => <div className="headline-card" key={title}><span>{title}</span><strong>{money(value)}</strong><small>{note}</small></div>)}
        </div>
        <div className="kpis">
          {kpis.map(([title, value, note], i) => <div className={"kpi " + (i === 2 ? "featured" : "")} key={title}><div><span>{title}</span></div><strong>{typeof value === "number" ? money(value) : value}</strong><small>{note}</small></div>)}
        </div>
        <div className="panel report-loading-inline">
          <strong>Основные показатели готовы.</strong>
          <p>{reportError ? "Не удалось загрузить детализацию отчёта." : "Загружаются графики, склад и расшифровка операций."}</p>
          {reportError && <ErrorBox error={reportError} />}
        </div>
      </>
    );
  }
  if ((!usesDashboard && page !== "forecast" && reportLoading)) return <Spinner />;
  if (!usesDashboard && page !== "forecast" && reportError) return <ErrorBox error={reportError} />;
  if (page === "alerts")
    return (
      <>
        <div className="panel">
          <div className="panel-heading">
            <h2>Автоматические проверки ERP</h2>
            <span className="badge amber">{systemAlerts?.count ?? "…"}</span>
          </div>
          {systemAlertsError ? <ErrorBox error={systemAlertsError} /> :
            systemAlerts?.items?.length ? <div className="alert-list">{systemAlerts.items.map((item, index) =>
              <div className={`alert-item ${item.severity || "info"}`} key={`${item.type}-${item.account_id || "all"}-${index}`}>
                <strong>{item.title}</strong>
                {item.action && <p>{item.action}</p>}
              </div>)}
            </div> : <Empty title="Критических проверок нет" />}
        </div>
        <div className="panel">
          <div className="panel-heading">
            <h2>Остатки требуют внимания</h2>
            <span className="badge amber">{r.stock_alerts.length} SKU</span>
          </div>
          <Table rows={r.stock_alerts} cols={columns.stock} />
        </div>
        <div className="panel">
          <div className="panel-heading">
            <h2>Просроченные оплаты</h2>
          </div>
          <Table
            rows={r.receivables.filter((x) => x.overdue)}
            cols={["reference", "channel", "due", "due_date"]}
            refs={ctx.refs}
          />
        </div>
      </>
    );
  if (page === "forecast") return <Forecast ctx={ctx} />;
  if (page === "profit" || page === "accounting")
    return (
      <>
        <CostPendingNotice report={r} ctx={ctx} />
        <div className="report-grid">
          <div className="panel">
            <div className="panel-heading">
              <h2>Отчёт о прибыли и убытках</h2>{r.profit_complete === false && <span className="badge amber">Ожидается себестоимость / обработка операций</span>}
              <div className="heading-actions">
                <span>{ctx.start} — {ctx.end}</span>
                <a className="button secondary" href={`/api/reports/executive.xlsx?start=${ctx.start}&end=${ctx.end}${ctx.company ? `&company_id=${ctx.company}` : ""}`}>Скачать XLSX</a>
              </div>
            </div>
            {[
              ["Выручка за вычетом возвратов", r.revenue, "revenue"],
              ["Себестоимость проданного", r.cogs == null ? null : -r.cogs, "cogs"],
              ["Валовая прибыль", r.gross_profit, "gross_profit"],
              [r.commission_estimated > 0 ? "Комиссии (Kaspi включает оценку)" : "Комиссии", -r.commission, "commission"],
              ["Логистика", -r.logistics, "logistics"],
              ["Реклама", -r.advertising, "advertising"],
              ["Операционные расходы", -r.expenses, "expenses"],
              ["Чистая прибыль", r.net_profit, "net_profit"],
            ].map(([k, v, metric], i) => (
              <button
                type="button"
                className={
                  "statement-line statement-drill " + ([2, 7].includes(i) ? "total" : "")
                }
                key={k}
                onClick={() => setDetailMetric({ metric, title: k })}
                title="Показать, из каких операций получилась сумма"
              >
                <span>{k}<small>{metric === "commission" && r.commission_estimated > 0 ? `Расчётная комиссия Kaspi: ${money(-r.commission_estimated)} · открыть детализацию` : "Показать операции"}</small></span>
                <strong>{money(v)}</strong>
              </button>
            ))}
            <p className="panel-note">
              Налоги входят в прибыль только после регистрации расхода «Налоги».
              Автоматический налоговый расчёт и регламентированная отчётность не
              подключены.
            </p>
            {r.commission_estimate_suppressed && (
              <p className="panel-note amber">
                Оценка комиссии Kaspi пропущена: за этот период внесена фактическая комиссия. Проверьте, что она покрывает весь период.
              </p>
            )}
          </div>
          <div className="panel">
            <div className="panel-heading">
              <h2>Активы и расчёты на {ctx.end}</h2>
            </div>
            {[
              ["Деньги", r.cash, "cash"],
              ["Стоимость остатков", r.stock_value, "stock_value"],
              ["B2B задолженность", r.b2b_debt, "b2b_debt"],
              ["К возврату покупателям", r.refunds_payable, "refunds_payable"],
              ["Денежный поток за период", r.cash_flow, "cash_flow"],
            ].map(([k, v, metric]) => (
              <button type="button" className="statement-line statement-drill" key={k} onClick={() => setDetailMetric({ metric, title: k })}>
                <span>{k}<small>Показать расшифровку</small></span>
                <strong>{money(v)}</strong>
              </button>
            ))}
            <p className="panel-note">
              Стоимость склада — актив, а не расход периода. Оплата закупки
              отражается в Cash Flow отдельно от прибыли.
            </p>
            {page === "accounting" && (
              <div className="export-links">
                <a className="secondary" href={`/api/export/sales?format=xlsx&start=${ctx.start}&end=${ctx.end}${ctx.company ? `&company_id=${ctx.company}` : ""}`}>
                  Продажи XLSX
                </a>
                <a className="secondary" href={`/api/export/cash?format=xlsx&start=${ctx.start}&end=${ctx.end}${ctx.company ? `&company_id=${ctx.company}` : ""}`}>
                  Деньги XLSX
                </a>
                <a
                  className="secondary"
                  href={`/api/export/expenses?format=xlsx&start=${ctx.start}&end=${ctx.end}${ctx.company ? `&company_id=${ctx.company}` : ""}`}
                >
                  Расходы XLSX
                </a>
              </div>
            )}
          </div>
        </div>
        <div className="panel cashflow-panel">
          <div className="panel-heading">
            <div><h2>Cash Flow за период</h2><span>Движение реальных денег, отдельно от прибыли</span></div>
          </div>
          <div className="secondary-kpis compact-kpis">
            <div><span>На начало</span><strong>{money(r.cash_opening || 0)}</strong></div>
            <div><span>Поступления</span><strong>{money(r.cash_inflow || 0)}</strong></div>
            <div><span>Выплаты</span><strong>{money(r.cash_outflow || 0)}</strong></div>
            <div><span>Чистый поток</span><strong>{money(r.cash_flow || 0)}</strong></div>
            <div><span>На конец</span><strong>{money(r.cash_closing ?? r.cash)}</strong></div>
          </div>
          <Table rows={r.cash_by_category || []} cols={["category", "inflow", "outflow", "net"]} />
        </div>
        <div className="panel">
          <div className="panel-heading">
            <h2>Дебиторская задолженность</h2>
          </div>
          <Table
            rows={r.receivables}
            cols={[
              "reference",
              "channel",
              "customer_id",
              "due",
              "due_date",
              "overdue",
            ]}
            refs={ctx.refs}
          />
        </div>
            {detailMetric && <ReportDetails ctx={ctx} detail={detailMetric} onClose={() => setDetailMetric(null)} activeOnly={usesDashboard} />}
      </>
    );
  const headline = [
    ["Оборот сегодня", dash.today.revenue, "На " + dash.as_of],
    ["Прибыль сегодня", dash.today.net_profit, "Чистая прибыль"],
    ["Оборот месяца", dash.month.revenue, "С начала месяца"],
    ["Валовая прибыль месяца", dash.month.gross_profit, "С начала месяца"],
    ["Чистая прибыль месяца", dash.month.net_profit, "С начала месяца"],
  ];
  const kpis = [
    ["Оборот", r.revenue, "За вычетом возвратов", Wallet],
    ["Валовая прибыль", r.gross_profit, "Выручка − себестоимость", Layers],
    ["Чистая прибыль", r.net_profit, "После учтённых расходов", TrendingUp],
    [
      "Маржинальность",
      r.margin == null ? "—" : decimal(r.margin) + "%",
      "Чистая прибыль / выручка",
      ChartIcon,
    ],
  ];
  return (
    <>
      <CostPendingNotice report={r} ctx={ctx} />
      <div className="dashboard-headline">
        {headline.map(([title, value, note]) => (
          <div className="headline-card" key={title}><span>{title}</span><strong>{money(value)}</strong><small>{note}</small></div>
        ))}
      </div>
      <div className="kpis">
        {kpis.map(([title, value, note, I], i) => (
          <div className={"kpi " + (i === 2 ? "featured" : "")} key={title}>
            <div>
              <span>{title}</span>
              <I size={18} />
            </div>
            <strong>{typeof value === "number" ? money(value) : value}</strong>
            <small>{note}</smal…34118 tokens truncated…] = useState(false),
    [docs, setDocs] = useState([]),
    [agents, setAgents] = useState([]),
    [agent, setAgent] = useState("rick"),
    [designMode, setDesignMode] = useState("main_photo"),
    [variants, setVariants] = useState(1),
    [products, setProducts] = useState([]),
    [productId, setProductId] = useState(""),
    [studioCard, setStudioCard] = useState(null);
  useEffect(() => {
    if (page === "assistant") api("/ai/agents").then((d) => setAgents(d.items || [])).catch(() => {});
    api("/data/documents?limit=100").then((d) => setDocs(d.items)).catch(() => {});
    if (["content","designer"].includes(page)) api("/data/products?limit=200").then((d)=>setProducts(d.items||[])).catch(()=>{});
  }, [page, ctx.refresh]);
  // Hooks must be called in the same order when the user switches between
  // Assistant, Content and Designer. This return is intentionally after all
  // hooks, fixing the former production-only conditional-Hooks crash.
  if (page === "assistant") return <AIWorkspace ctx={ctx} enabled={enabled}/>;
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      let j = await api("/jobs", {
        method: "POST",
        body: {
          kind: page,
          payload: {
            question: text,
            agent: page === "assistant" ? agent : undefined,
            facts: text,
            prompt: text,
            document_id: doc ? Number(doc) : null,
            product_id: productId ? Number(productId) : null,
            company_id: ctx.company
              ? Number(ctx.company)
              : page === "assistant"
                ? null
                : ctx.refs.companies?.[0]?.id,
            start: ctx.start,
            end: ctx.end,
            mode: page === "designer" ? designMode : undefined,
            variants: page === "designer" ? Number(variants) : undefined,
          },
        },
      });
      setJob(j);
      if (["queued", "running"].includes(j.status)) j = await waitForAIJob(j.id, setJob);
      setJob(j);
      if (j.status === "failed") throw new Error(j.error || "AI-задача завершилась с ошибкой");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="ai-layout">
      <div className="panel ai-main">
        <div className="ai-title">
          <div className="ai-orb">
            <Sparkles size={25} />
          </div>
          <div>
            <h2>
              {page === "assistant"
                ? (agents.find((a) => a.id === agent)?.name || "Рик") + " · " + (agents.find((a) => a.id === agent)?.title || "AI-руководитель")
                : page === "content"
                  ? "Карточка из фактов о товаре"
                  : "Новая визуальная идея"}
            </h2>
            <p>
              {page === "assistant"
                ? (agent === "rick" ? "Главная точка общения: Рик помогает владельцу увидеть картину бизнеса и выбрать действие." : "Специализированный AI работает только в своей зоне и использует проверенные данные ERP.")
                : page === "content"
                  ? "Укажите характеристики поставщика и выберите загруженное фото."
                  : "Опишите композицию, фон и настроение изображения."}
            </p>
          </div>
        </div>
        {!enabled && (
          <div className="info-banner">
            AI API пока не подключён. Укажите OPENAI_API_KEY на сервере.
            Финансовая аналитика и калькулятор работают без ключа.
          </div>
        )}
        {page === "assistant" && (
          <div className="ai-team">
            <div className="ai-team-head"><span className="eyebrow">AI-КОМАНДА</span><strong>Выберите специалиста или пишите Рику</strong></div>
            <div className="agent-strip">
              {agents.map((a) => (
                <button type="button" key={a.id} className={`agent-card ${agent === a.id ? "active" : ""}`} onClick={() => setAgent(a.id)}>
                  <span className="agent-avatar">{a.name.slice(0,1)}</span>
                  <span><b>{a.name}</b><small>{a.title}</small><em>{a.scope}</em></span>
                </button>
              ))}
            </div>
          </div>
        )}
        {page === "assistant" && (
          <div className="prompt-chips">
            {[
              "Сколько мы заработали в этом месяце?",
              "Какой канал самый прибыльный?",
              "Какие товары скоро закончатся?",
              "Какие товары плохо продаются?",
            ].map((p) => (
              <button className="secondary" key={p} onClick={() => setText(p)}>
                {p}
              </button>
            ))}
          </div>
        )}
        <form onSubmit={submit}>
          <label>
            {page === "assistant"
              ? "Ваш вопрос"
              : page === "content"
                ? "Характеристики поставщика"
                : "Задание для дизайнера"}
            <textarea
              rows={page === "assistant" ? 4 : 7}
              required
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={
                page === "content"
                  ? "Укажите только известные свойства: название, размер, цвет, материал…"
                  : "Напишите здесь…"
              }
            />
          </label>
          {["content", "designer"].includes(page) && (<label>Товар из ERP<select value={productId} onChange={(e)=>setProductId(e.target.value)}><option value="">Выберите товар</option>{products.map(p=><option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}</select></label>)}
          {["content", "designer"].includes(page) && (
            <label>
              {page === "designer" ? "Исходная фотография товара (обязательно)" : "Фотография товара"}
              <select value={doc} onChange={(e) => setDoc(e.target.value)}>
                <option value="">Без фотографии</option>
                {docs
                  .filter((d) => d.mime.startsWith("image/"))
                  .map((d) => (
                    <option value={d.id} key={d.id}>
                      {d.name}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {page === "designer" && (
            <div className="form-grid two">
              <label>Режим<select value={designMode} onChange={(e)=>setDesignMode(e.target.value)}>
                <option value="main_photo">Marketplace main photo</option><option value="background">Замена/очистка фона</option>
                <option value="enhance">Улучшение качества</option><option value="infographic">Инфографика</option>
                <option value="banner">Баннер</option><option value="lifestyle">Lifestyle</option><option value="creative">Рекламный креатив</option>
              </select></label>
              <label>Вариантов<select value={variants} onChange={(e)=>setVariants(e.target.value)}><option>1</option><option>2</option><option>3</option><option>4</option></select></label>
            </div>
          )}
          <button
            className="primary"
            disabled={
              !enabled || busy || (page === "designer" && !doc) || (job && ["queued", "running"].includes(job.status))
            }
          >
            <Sparkles size={17} />
            {page === "assistant" ? "Получить анализ" : "Создать"}
          </button>
        </form>
        <ErrorBox error={error} />
        {job && (
          <div className="ai-result">
            <span className="badge gray">
              Задание #{job.id} · {job.status}
            </span>
            {["queued", "running"].includes(job.status) && <Spinner />}
            <ErrorBox error={job.error} />
            {job.status === "failed" && job.attempts < 3 && (
              <button
                className="secondary"
                onClick={() =>
                  api("/jobs/" + job.id + "/retry", { method: "POST" })
                    .then(setJob)
                    .catch((e) => setError(e.message))
                }
              >
                Повторить
              </button>
            )}
            {job.status === "done" && (
              <>
                <div className="ai-answer">
                  {job.result.answer || job.result.text || job.result.notice}
                </div>
                {job.result.document_ids?.length > 1 && <div className="studio-variants"><h3>AI-варианты</h3><div className="variant-grid">{job.result.document_ids.map((id,i)=><button type="button" key={id} className="variant-card" onClick={()=>setDoc(String(id))}><img src={`/api/documents/${id}/download`}/><b>Вариант {i+1}</b><small>{String(doc)===String(id)?"Выбран":"Выбрать"}</small></button>)}</div></div>}
                {job.result.document_id && (
                  <a
                    className="secondary"
                    href={
                      "/api/documents/" + job.result.document_id + "/download"
                    }
                  >
                    <Download size={16} />
                    Скачать изображение
                  </a>
                )}
                {page === "designer" && job.result.document_id && productId && <div className="studio-actions"><button type="button" className="primary" onClick={async()=>{try{const card=await api("/product-studio/cards",{method:"POST",body:{product_id:Number(productId),company_id:ctx.company?Number(ctx.company):undefined,marketplace:"kaspi",image_document_ids:[Number(doc||job.result.document_id)],title:products.find(p=>String(p.id)===String(productId))?.name||"",description:text,characteristics:{}}});setStudioCard(card)}catch(e){setError(e.message)}}}>Проверить карточку Kaspi</button>{studioCard&&<div className={`validation-box ${studioCard.validation?.passed?"ok":"bad"}`}><b>{studioCard.validation?.passed?"QOR Validator: пройден":"Нужно исправить"}</b>{studioCard.validation?.errors?.map(x=><small key={x}>{x}</small>)}{studioCard.validation?.passed&&<button type="button" className="secondary" onClick={()=>api(`/product-studio/cards/${studioCard.id}/publish`,{method:"POST",body:{review_days:7,auto_optimize:true,auto_publish:false,rollback:true,max_generations:3}}).then(setStudioCard).catch(e=>setError(e.message))}>Запустить · контроль через 7 дней</button>}</div>}</div>}
                {job.result.data && (
                  <>
                    <h3>Проверенные показатели</h3>
                    <div className="secondary-kpis">
                      {[
                        ["Выручка", job.result.data.revenue],
                        ["Чистая прибыль", job.result.data.net_profit],
                        ["Деньги", job.result.data.cash],
                      ].map(([k, v]) => (
                        <div key={k}>
                          <span>{k}</span>
                          <strong>{money(v)}</strong>
                        </div>
                      ))}
                    </div>
                    <p className="muted">
                      Источник: {job.result.source}. Период:{" "}
                      {job.result.period?.join(" — ")}
                    </p>
                  </>
                )}
              </>
            )}
          </div>
        )}
      </div>
      <div className="panel ai-side">
        <span className="eyebrow">КОНТРОЛЬ ДАННЫХ</span>
        <h3>
          {page === "assistant"
            ? "Цифры из системы"
            : "Только подтверждённые факты"}
        </h3>
        <p>
          {page === "assistant"
            ? "Выручку, себестоимость, прибыль и остатки рассчитывает финансовое ядро. AI получает готовый отчёт в пределах ваших прав."
            : "Неизвестные характеристики требуют уточнения. Проверьте текст и изображение перед публикацией на маркетплейсе."}
        </p>
        <div className="rule">
          <ShieldCheck size={18} />
          <span>AI не изменяет финансовые записи</span>
        </div>
        <div className="rule">
          <FileText size={18} />
          <span>
            Данные отправляются в настроенный AI API только по запросу
          </span>
        </div>
        {page === "content" && (
          <button
            className="secondary"
            onClick={() => ctx.navigate("documents")}
          >
            Загрузить фото товара
          </button>
        )}
      </div>
    </div>
  );
}
function Calculator() {
  const [v, setV] = useState({
      quantity: 5000, purchase_price: 20, fx_rate: 70, price: 3990,
      delivery: 350000, customs: 120000, broker: 50000, certification: 40000,
      packaging: 100000, other_import: 30000, commission_percent: 12,
      marketplace_logistics_unit: 180, advertising_percent: 5, advertising: 0,
      return_percent: 5, target_margin_percent: 20,
    }), [result, setResult] = useState(null), [error, setError] = useState("");
  const fields = {
    quantity:"Количество, шт", purchase_price:"Закупочная цена, валюта", fx_rate:"Курс к ₸",
    price:"Плановая цена продажи, ₸", delivery:"Китай → Казахстан, ₸", customs:"Таможня, ₸",
    broker:"Брокер, ₸", certification:"Сертификат, ₸", packaging:"Упаковка, ₸",
    other_import:"Прочие импортные расходы, ₸", commission_percent:"Комиссия marketplace, %",
    marketplace_logistics_unit:"Логистика marketplace / шт, ₸", advertising_percent:"Реклама, % от выручки",
    advertising:"Фиксированная реклама, ₸", return_percent:"Возвраты, %", target_margin_percent:"Целевая чистая маржа, %",
  };
  const submit=async(e)=>{e.preventDefault();try{setResult(await api("/calculator",{method:"POST",body:v}));setError("")}catch(e){setError(e.message)}};
  const rows = result ? [
    ["full_cost_total","Полный Full Cost партии"],["full_cost_unit","Full Cost / шт"],["capital_required","Необходимый капитал"],
    ["revenue","Ожидаемая выручка"],["cogs","COGS"],["gross_profit","Валовая прибыль"],["commission","Комиссия"],
    ["marketplace_logistics","Логистика marketplace"],["advertising","Реклама"],["net_profit","Чистая прибыль"],
    ["minimum_price","Минимальная цена"],["recommended_price","Рекомендованная цена"],
  ] : [];
  return <div className="report-grid">
    <form className="panel padded" onSubmit={submit}><h2>AI Product Calculator</h2><p className="muted">Финансовое ядро считает детерминированно — AI не придумывает цифры.</p>
      <div className="form-grid">{Object.entries(fields).map(([k,l])=><label key={k}>{l}<input required type="number" min={k==="quantity"?1:0} step="any" value={v[k]} onChange={e=>setV({...v,[k]:e.target.value})}/></label>)}</div>
      <ErrorBox error={error}/><button className="primary">Рассчитать экономику</button></form>
    <div className="panel padded"><h2>Результат сценария</h2>{result?<><div className="calc-profit"><span>{result.decision}</span><strong>{decimal(result.net_profit)} ₸</strong></div>
      {rows.map(([k,l])=><div className="statement-line" key={k}><span>{l}</span><strong>{decimal(result[k])} ₸</strong></div>)}
      <div className="statement-line"><span>Маржа</span><strong>{decimal(result.margin_percent)}%</strong></div><div className="statement-line"><span>ROI</span><strong>{decimal(result.roi_percent)}%</strong></div>
      <div className="statement-line"><span>Break-even</span><strong>{result.break_even_units ?? "—"} шт</strong></div><p className="muted">{result.turnover_notice}</p><p className="muted">{result.method}</p></>:<Empty text="Введите параметры и нажмите «Рассчитать экономику»"/>}</div>
  </div>;
}
const IMPORT_ALIASES = {
  reference:["reference","номер","номер заказа","заказ","order id","order_id","id заказа","документ"],
  external_id:["external_id","номер заказа","код заказа","id заказа","order id","order_id","номер документа"],
  event_type:["event_type","тип операции","операция"],

  date:["date","дата","дата продажи","дата заказа","күн","сату күні"],
  company_id:["company_id","компания id","id компании"], account_id:["account_id","аккаунт id","канал id"],
  product_id:["product_id","товар id","id товара"], customer_id:["customer_id","клиент id","id клиента"],
  sku:["sku","артикул","артикул продавца","vendor code","код товара"], name:["name","товар","наименование","название товара","өнім"],
  category:["category","категория","санат"], quantity:["quantity","количество","кол-во","qty","штук","саны"],
  unit_price:["unit_price","цена продажи","цена","стоимость","price","сумма за единицу","сумма продажи","сумма заказа","сумма"],
 price:["price","цена","розничная цена"],
  unit_cost:["unit_cost","себестоимость","закупочная цена","цена закупки","cost"], commission:["commission","комиссия","комиссия маркетплейса","комиссия kaspi","комиссия банка"],

  logistics:["logistics","логистика","доставка","логистика kaspi","доставка kaspi","стоимость доставки для продавца","доставка за счет продавца","доставка за счёт продавца","расходы на доставку"],
 advertising:["advertising","реклама","рекламные расходы"], paid:["paid","оплачено","оплата"],
  amount:["amount","сумма","расход","сумма расхода"], description:["description","описание","назначение"], category_expense:["категория расхода"],
  supplier:["supplier","поставщик"], extra_cost:["extra_cost","доп расходы","дополнительные расходы"], currency:["currency","валюта"], fx_rate:["fx_rate","курс"],
  min_stock:["min_stock","минимальный остаток"], reason:["reason","причина"], project:["project","проект"], payment_method:["payment_method","способ оплаты"]
};
function normHeader(v){return String(v||"").trim().toLowerCase().replace(/[._-]+/g," ").replace(/\s+/g," ")}
function autoImportMapping(fields, headers){
  const normalized=headers.map(h=>[h,normHeader(h)]); const out={};
  for(const f of fields){ const aliases=[f,...(IMPORT_ALIASES[f]||[])].map(normHeader); const hits=normalized.filter(([,h])=>aliases.includes(h)); if(hits.length===1) out[f]=hits[0][0]; }
  return out;
}
function prepareKaspiReportRows(rows, headers, accountId) {
  const norm = (v) => normHeader(v).replace(/ё/g,"е");
  const find = (aliases) => {
    for (const alias of aliases) {
      const hit = headers.find((h) => norm(h) === alias);
      if (hit) return hit;
    }
    return null;
  };
  const orderCol = find(["номер заказа","код заказа","id заказа","order id","order_id","заказ"]);
  const statusCol = find(["статус заказа","статус","состояние заказа","order status"]);
  const operationCol = find(["тип операции","операция","вид операции","тип транзакции","operation","transaction type"]);
  const skuCol = find(["артикул продавца","артикул","sku","vendor code","код товара"]);
  const lineCol = find(["id позиции","код позиции","номер позиции","order entry id","entry id","line id"]);
  const dateCol = find(["дата продажи","дата выдачи","дата завершения заказа","дата завершения","дата операции","sale date","completion date","дата заказа","дата","order date"]);
  const qtyCol = find(["количество","кол во","qty","quantity","саны"]);
  const totalSaleCol = find(["сумма продажи","сумма товара","стоимость товара","сумма по позиции","итого по товару","line total","total price","totalprice","сумма заказа","сумма"]);
  const unitSaleCol = find(["цена за единицу","цена товара","цена продажи","unit price","unit_price","price"]);
  const saleCol = totalSaleCol || unitSaleCol;
  const commissionCol = find(["комиссия kaspi","комиссия банка","комиссия маркетплейса","комиссия"]);
  const orderCommissionCol = find(["комиссия за заказ","order commission"]);
  const sellerDeliveryCol = find(["стоимость доставки для продавца","доставка за счет продавца","доставка за счёт продавца","логистика kaspi","логистика","расходы на доставку"]);
  const buyerDeliveryCol = find(["стоимость доставки для покупателя","доставка за счет покупателя","доставка за счёт покупателя","стоимость доставки"]);
  const discountCol = find(["скидка","скидка на товар","discount"]);
  const refundCol = find(["сумма возврата","возврат средств","сумма возврата покупателю","refund","refund amount"]);
  if (!orderCol || !skuCol || !dateCol || !saleCol) return null;
  const numeric = (v) => Number(String(v ?? "").replace(/[\s\u00a0\u202f]/g,"").replace(",", ".")) || 0;
  const out = [];
  const seenOrderCharges = new Set();
  for (const row of rows) {
    const id = String(row[orderCol] || "").trim();
    if (!id) continue;
    const status = norm((statusCol && row[statusCol]) || (operationCol && row[operationCol]) || "");
    const sku = String(row[skuCol] || "").trim();
    const lineId = lineCol && row[lineCol] ? id + ":" + String(row[lineCol]).trim() : (sku ? id + ":" + sku : id);
    const quantity = Math.max(1, Math.abs(numeric(qtyCol ? row[qtyCol] : 1) || 1));
    const amount = Math.abs(numeric(row[saleCol]));
    const unitPrice = totalSaleCol
      ? Math.ceil(amount * 100 / quantity) / 100
      : amount;
    const discount = totalSaleCol
      ? Math.max(0, Math.round((unitPrice * quantity - amount) * 100) / 100)
      : Math.abs(numeric(discountCol ? row[discountCol] : 0));
    const base = {
      ...row,
      __qor_order_id: id,
      __qor_date: row[dateCol] || "",
      __qor_sku: row[skuCol] || "",
      __qor_quantity: quantity,
      __qor_unit_price: unitPrice,
      __qor_discount: discount,
      __qor_refund: refundCol ? Math.abs(numeric(row[refundCol])) : amount,
      __qor_sale_reference: "Kaspi:" + accountId + ":" + lineId,
    };
    const cancelled = /(отмен|cancel|cancell)/.test(status);
    const returned = /(возврат|вернул|return|refund)/.test(status);
    const completed = /(выдан|заверш|получен|completed|delivered|продаж|sale)/.test(status);
    const isSaleReportRow = !statusCol && !operationCol;
    if (cancelled) {
      out.push({...base,__qor_event_type:"order",__qor_external_id:lineId});
    } else if (returned) {
      out.push({...base,__qor_event_type:"return",__qor_external_id:lineId+":return"});
    } else if (completed || isSaleReportRow) {
      out.push({...base,__qor_event_type:"sale",__qor_external_id:lineId});
    } else {
      out.push({...base,__qor_event_type:"order",__qor_external_id:lineId});
    }
    const commission = commissionCol ? Math.abs(numeric(row[commissionCol])) : 0;
    const commissionIdentity = orderCommissionCol === commissionCol ? id : lineId;
    const commissionKey = commissionIdentity + ":commission:" + commission;
    if (commission > 0 && !seenOrderCharges.has(commissionKey)) {
      seenOrderCharges.add(commissionKey);
      out.push({...base,__qor_event_type:"commission",__qor_external_id:commissionIdentity+":commission",__qor_amount:commission});
    }
    const sellerDelivery = sellerDeliveryCol ? Math.abs(numeric(row[sellerDeliveryCol])) : 0;
    const deliveryKey = id + ":logistics:" + sellerDelivery;
    if (sellerDelivery > 0 && !seenOrderCharges.has(deliveryKey)) {
      seenOrderCharges.add(deliveryKey);
      out.push({...base,__qor_event_type:"logistics",__qor_external_id:id+":logistics",__qor_amount:sellerDelivery});
    }
    if (buyerDeliveryCol) base.__qor_buyer_delivery = row[buyerDeliveryCol];
  }
  return out;
}
function Imports({ ctx }) {
  const [kind, setKind] = useState("products"),
    [sourceFile,setSourceFile] = useState(null),
    [sheet,setSheet] = useState(""), [headerRow,setHeaderRow] = useState(""),
    [parsed, setParsed] = useState(null),
    [mapping, setMapping] = useState({}),
    [fields, setFields] = useState([]),
    [preview, setPreview] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const kinds = {
    opening: "Начальные остатки / историческая себестоимость",
    products: "Товары",
    sales: "Продажи",
    returns: "Возвраты",
    stock: "Остатки (изменения)",
    purchases: "Закупки",
    expenses: "Расходы",
    b2b: "B2B продажи",
    reports: "Продажи из отчёта",
    marketplace_reports: "Отчёт маркетплейса (продажи / возвраты / остатки)",
    bank: "Банк / деньги",
  };
  useEffect(() => {
    api("/import/fields/" + kind)
      .then((d) => setFields(d.fields))
      .catch((e) => setError(e.message));
    setParsed(null);
    setSourceFile(null);setSheet("");setHeaderRow("");
    setPreview(null);
    setMapping({});
  }, [kind]);
  const parse = async (e) => {
    const file = e?.target?.files?.[0] || sourceFile;
    if (!file) return;
    setError("");
    setBusy(true);
    setPreview(null);
    try {
      const f = new FormData();
      f.append("file", file);
      if (!e && sheet) f.append("sheet",sheet);
      if (!e && headerRow) f.append("header_row",headerRow);
      const definitions = await api("/import/fields/" + kind);
      const d = await api("/import/parse", { method: "POST", body: f });
      setSourceFile(file);setSheet(d.selected_sheet || "");setHeaderRow(String(d.header_row || 1));
      const defaultAccount = ctx.refs.accounts?.find((x) => x.channel === "Kaspi" && (!ctx.company || x.company_id == ctx.company));
      const kaspiRows = kind === "marketplace_reports" && defaultAccount
        ? prepareKaspiReportRows(d.rows, d.headers, defaultAccount.id) : null;
      if (kaspiRows) {
        const synthetic = {...d, rows: kaspiRows};
        setParsed(synthetic);
        setMapping({
          event_type:"__qor_event_type", external_id:"__qor_external_id", date:"__qor_date",
          sku:"__qor_sku", quantity:"__qor_quantity", unit_price:"__qor_unit_price",
          discount:"__qor_discount", refund:"__qor_refund", sale_reference:"__qor_sale_reference", amount:"__qor_amount",
        });
      } else {
        setParsed(d);
        setMapping(autoImportMapping(definitions.fields, d.headers));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      if (e) e.target.value = "";
    }
  };
  const validate = async () => {
    setBusy(true);
    setError("");
    try {
      setPreview(
        await api("/import/preview", {
          method: "POST",
          body: { kind, rows: parsed.rows, mapping, defaults: {
            company_id: ctx.company || ctx.refs.companies?.[0]?.id || null,
            account_id: kind === "marketplace_reports"
              ? (ctx.refs.accounts?.find(a => a.channel === "Kaspi" && (!ctx.company || a.company_id == ctx.company))?.id || null)
              : ((kind === "sales" || kind === "reports")
                ? (ctx.refs.accounts?.find(a => a.channel === "Offline" && (!ctx.company || a.company_id == ctx.company))?.id || null)
                : (kind === "b2b" ? (ctx.refs.accounts?.find(a => a.channel === "B2B" && (!ctx.company || a.company_id == ctx.company))?.id || null) : null))
          } },
        }),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const commit = async () => {
    setBusy(true);
    setError("");
    try {
      const d = await api("/import/" + preview.id + "/confirm", {
        method: "POST",
      });
      ctx.notify("Импортировано строк: " + d.count);
      setParsed(null);
      setPreview(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="panel padded">
        <div className="import-steps">
          <span className="selected">01 Файл</span>
          <span className={parsed ? "selected" : ""}>02 Сопоставление</span>
          <span className={preview ? "selected" : ""}>
            03 Проверка и импорт
          </span>
        </div>
        <div className="import-top">
          <label>
            Что импортируем
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(kinds).map(([k, l]) => (
                <option value={k} key={k}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <a
            className="secondary"
            href={"/api/templates/" + kind + "?format=xlsx"}
          >
            <Download size={16} />
            Шаблон XLSX
          </a>
          <a
            className="secondary"
            href={"/api/export/" + kind + "?format=xlsx"}
          >
            <Download size={16} />
            Экспорт
          </a>
        </div>
        <label className="dropzone">
          <Upload size={28} />
          <strong>{busy ? "Обрабатываем…" : "Выбрать CSV или Excel"}</strong>
          <span>UTF-8 CSV / XLSX · до 5 МБ · до 5000 строк</span>
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={parse}
            disabled={busy}
          />
        </label>
        <p className="muted">
          {kind === "opening"
            ? "Для прибыли Wildberries загрузите Excel поставщика: Артикул/SKU, Количество, Себестоимость, Дата, Валюта и Номер. Артикул WB сопоставляется с товаром из API автоматически. Дата себестоимости должна быть не позже продажи — после импорта система пересчитает COGS и прибыль, не создавая повторных продаж."
            : "QOR автоматически распознаёт распространённые названия колонок на русском/казахском/английском. Для продаж товар можно указать по SKU/артикулу — ID товара подставится автоматически; выбранная компания и Offline/B2B канал также подставляются автоматически. Перед записью всегда показывается проверка. Остатки задаются изменением, финансовые строки требуют уникального номера/reference."}
        </p>
        <ErrorBox error={error} />
        {parsed && (
          <>
            <h3>Сопоставление колонок · {parsed.count} строк</h3>
            <div className="row-actions">{parsed.sheets && <label>Лист<select value={sheet} onChange={e=>setSheet(e.target.value)}>{parsed.sheets.map(name=><option key={name}>{name}</option>)}</select></label>}<label>Строка заголовков<input type="number" min="1" max="20" value={headerRow} onChange={e=>setHeaderRow(e.target.value)}/></label><button disabled={busy} onClick={()=>parse()}>Перечитать файл</button></div>
            <div className="mapping-grid">
              {fields.map((f) => (
                <label key={f}>
                  {labels[f] || f}
                  <small>{f}</small>
                  <select
                    value={mapping[f] || ""}
                    onChange={(e) => {
                      const m = { ...mapping };
                      if (e.target.value) m[f] = e.target.value;
                      else delete m[f];
                      setMapping(m);
                      setPreview(null);
                    }}
                  >
                    <option value="">Не импортировать</option>
                    {parsed.headers.map((h) => (
                      <option key={h}>{h}</option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <h3>Первые строки файла</h3>
            <Table raw
                rows={parsed.rows.slice(0, 5)} cols={parsed.headers} />
            <button className="primary" disabled={busy} onClick={validate}>
              Проверить перед импортом
            </button>
          </>
        )}
        {preview && (
          <div className="preview">
            <h3>
              {preview.errors.length
                ? "Найдены ошибки: " + preview.errors.length
                : "Проверка пройдена"}
            </h3>
            {preview.errors.length ? (
              <>
                <Table rows={preview.errors} cols={["row", "error"]} />
                <a
                  className="secondary"
                  href={"/api/import/" + preview.id + "/errors"}
                >
                  Скачать отчёт ошибок
                </a>
              </>
            ) : (
              <>
                <p>
                  Будут проведены все {preview.count} строк одной транзакцией.
                  При конфликте ни одна строка не будет сохранена.
                </p>
                <button className="primary" disabled={busy} onClick={commit}>
                  Подтвердить импорт {preview.count} строк
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </>
  );
}
function Roles() {
  const { data, error, loading } = useLoad("/roles", 0);
  return loading ? (
    <Spinner />
  ) : error ? (
    <ErrorBox error={error} />
  ) : (
    <div className="role-grid">
      {Object.entries(data).map(([role, permissions]) => (
        <div className="panel padded" key={role}>
          <ShieldCheck size={25} />
          <h2>{role}</h2>
          <div className="permission-list">
            {permissions.map((p) => (
              <span className="badge gray" key={p}>
                {p === "*" ? "Полный доступ" : p}
              </span>
            ))}
          </div>
          <p className="muted">
            {role === "Owner"
              ? "Видит все компании и управляет пользователями."
              : "Доступ только к назначенным компаниям. :read — только чтение."}
          </p>
        </div>
      ))}
    </div>
  );
}
function Settings({ settings, ctx, onLogout }) {
  const [name, setName] = useState(settings.business_name || ""),
    [old, setOld] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState("");
  const save = async (e) => {
    e.preventDefault();
    try {
      await api("/settings", { method: "PUT", body: { business_name: name } });
      ctx.notify("Настройки сохранены");
    } catch (e) {
      setError(e.message);
    }
  };
  const change = async (e) => {
    e.preventDefault();
    try {
      await api("/auth/password", {
        method: "POST",
        body: { old, new: password },
      });
      onLogout();
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <div className="report-grid">
      <form className="panel padded" onSubmit={save}>
        <h2>Рабочее пространство</h2>
        <label>
          Название
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </label>
        <label>
          Валюта
          <input value="KZT · Казахстанский тенге" readOnly />
        </label>
        <label>
          Часовой пояс
          <input value="Asia/Almaty" readOnly />
        </label>
        <button className="primary">Сохранить</button>
        <p className="muted">
          AI: {settings.ai_enabled ? "подключён" : "ожидает OPENAI_API_KEY"}.
          Ключи хранятся на сервере, не в браузере.
        </p>
        <ErrorBox error={error} />
      </form>
      <form className="panel padded" onSubmit={change}>
        <h2>Изменить пароль</h2>
        <label>
          Текущий пароль
          <input
            type="password"
            value={old}
            onChange={(e) => setOld(e.target.value)}
            required
          />
        </label>
        <label>
          Новый пароль
          <input
            type="password"
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <button className="secondary">
          Обновить пароль и завершить сессии
        </button>
      </form>
    </div>
  );
}
