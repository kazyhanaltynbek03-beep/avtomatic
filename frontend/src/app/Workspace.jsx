Warning: truncated output (original token count: 86258)
Total output lines: 4711

import { useState, useEffect, useRef, useCallback, lazy, Suspense } from "react";
import {
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
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
  CalendarDays,
  TrendingUp,
  Layers,
  ShieldCheck,
  Paperclip,
  Copy,
  MessageSquare,
  Image as ImageIcon,
  Receipt,
  Store,
  Leaf,
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
const MarketplaceReturns = lazy(() => import("../features/MarketplaceReturns"));
const MarketplaceProductReport = lazy(() => import("../features/MarketplaceProductReport"));
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
    [notificationCount, setNotificationCount] = useState(0),
    [refs, setRefs] = useState({}),
    [company, setCompany] = useState(""),
    [range, setRange] = useState("Месяц"),
    [start, setStart] = useState(today().slice(0, 8) + "01"),
    [end, setEnd] = useState(today()),
    [modal, setModal] = useState(null),
    [settings, setSettings] = useState({});
  const [marketplaceStoreByChannel, setMarketplaceStoreByChannel] = useState({Kaspi:"", Wildberries:""});
  const [marketplaceReportChannel, setMarketplaceReportChannel] = useState("");
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
  }, [auth]);
  // Alerts are loaded on the notifications page. Fetching them in the background
  // runs two full report calculations and competes with the page the user opened.
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
  const current = flat.find((x) => x[0] === page) || flat[0];
  const marketplaceChannel = ["Kaspi", "Wildberries"].includes(page) ? page : "";
  const marketplaceAccounts = marketplaceChannel
    ? (refs.accounts || []).filter(a => a.active !== false && a.channel === marketplaceChannel && (!company || String(a.company_id) === String(company)))
    : [];
  const marketplaceAccountIds = marketplaceAccounts.map(a => String(a.id)).join(",");
  const marketplaceAccountId = marketplaceChannel ? (marketplaceStoreByChannel[marketplaceChannel] || "") : "";
  useEffect(() => {
    if (!marketplaceChannel || !marketplaceAccountId) return;
    if (!marketplaceAccountIds.split(",").includes(String(marketplaceAccountId))) {
      setMarketplaceStoreByChannel(current => ({...current, [marketplaceChannel]: ""}));
    }
  }, [marketplaceChannel, marketplaceAccountIds, marketplaceAccountId]);
  if (auth === undefined) return <Spinner />;
  if (!auth) return <Login onAuth={setAuth} />;
  const ctx = {
    auth,
    refs,
    company,
    start,
    end,
    refresh,
    marketplaceAccountId,
    marketplaceReportChannel,
    setMarketplaceReportChannel,
    onNotificationCount: setNotificationCount,
    notify,
    navigate,
    open: (kind, item) => setModal({ kind, item }),
    reload: () => setRefresh(value => value + 1),
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
          <span className="brand-mark"><Leaf size={18} strokeWidth={2.4}/></span>
          <span className="brand-word">QOR AI</span>
          <span className="workspace-tag">BUSINESS ERP</span>
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
                  <details
                    className="nav-group"
                    open={items.some((item) => item[0] === page)}
                  >
                    <summary>
                      <h4>{title}</h4>
                    </summary>
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
                  </details>
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
          <a className="mobile-brand" href="#dashboard" onClick={() => navigate("dashboard")} aria-label="QOR AI — главная">
            <span className="mobile-brand-mark"><Leaf size={20} strokeWidth={2.4}/></span>
            <span><b>QOR AI</b><small>BUSINESS ERP</small></span>
          </a>
          <div className="breadcrumb">
            Рабочее пространство <span>/</span> <strong>{current[1]}</strong>
          </div>
          <div className="header-right">
            {settings.demo && <span className="demo-badge">ДЕМО-ДАННЫЕ</span>}
            <span className="currency">KZT · ₸</span>
            {can(auth, "analytics") && (
              <button
                className="icon-button notification-button"
                onClick={() => navigate("alerts")}
                aria-label={notificationCount ? `Уведомления: ${notificationCount}` : "Уведомления"}
                title={notificationCount ? `${notificationCount} уведомлений` : "Уведомления"}
              >
                <Bell size={19} />
                {notificationCount > 0 && <span className="notification-count">{notificationCount > 99 ? "99+" : notificationCount}</span>}
              </button>
            )}
            <div className="avatar small">{auth.user.name[0]}</div>
          </div>
        </header>
        <main data-page={page}>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {["assistant", "niches", "content", "designer"].includes(page)
                  ? "INTELLIGENCE"
                  : page === "dashboard" || page === "analytics" ? "BUSINESS OVERVIEW" : "РАБОЧЕЕ ПРОСТРАНСТВО"}
              </div>
              <h1>{current[1]}</h1>
              <p>
                {page === "dashboard"
                  ? "Главные показатели и то, что требует вашего внимания."
                  : page === "stock"
                    ? "Один физический склад. Остатки разделены по владельцам."
                    : page === "accounts"
                      ? "Каналы продаж и отдельные аккаунты ваших компаний."
                    : page === "products"
                      ? "Создавайте основные SKU и связывайте с ними карточки разных Kaspi и Wildberries магазинов. Остаток ведётся в Едином складе."
                      : page === "marketplace-products"
                        ? "Здесь отдельно хранятся импортированные и связанные карточки площадок. Перенос ID на основной SKU сохраняет историю продаж."
                           : page === "cash"
                          ? "Записывайте фактические поступления и выплаты. Остаток денег и прибыль — разные показатели."
                          : page === "alerts"
                            ? "Проверяйте товары с низким остатком и платежи, срок которых уже наступил."
                      : "Данные рабочего пространства"}
              </p>
            </div>
            {[
              "dashboard",
              "sales",
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
                <>
                  {page === "dashboard" && <button className="secondary" onClick={() => { setMarketplaceReportChannel(""); navigate("marketplace-product-report"); }}>
                    <FileText size={17} /> Сводный отчёт по SKU
                  </button>}
                  <button className="primary" onClick={() => setModal({ kind: page === "dashboard" ? "sales" : page })}>
                    <Plus size={18} />
                    {page === "dashboard" ? "Новая продажа" : "Добавить"}
                  </button>
                </>
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
              "marketplace-product-report",
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
          {marketplaceChannel && <div className="marketplace-store-toolbar">
            <label htmlFor="marketplace-store-select">Магазин {marketplaceChannel}
              <select id="marketplace-store-select" aria-label={`Магазин ${marketplaceChannel}`} value={marketplaceAccountId} disabled={!marketplaceAccounts.length} onChange={e=>setMarketplaceStoreByChannel(current=>({...current,[marketplaceChannel]:e.target.value}))}>
                {marketplaceAccounts.length ? <><option value="">Все магазины {marketplaceChannel}</option>{marketplaceAccounts.map(account=><option key={account.id} value={account.id}>{account.name}</option>)}</> : <option value="">Нет подключённых магазинов</option>}
              </select>
            </label>
            <span>{marketplaceAccountId ? `Показаны данные магазина «${marketplaceAccounts.find(a=>String(a.id)===String(marketplaceAccountId))?.name || ""}».` : marketplaceAccounts.length ? `Показаны данные всех подключённых магазинов ${marketplaceChannel}.` : `Подключите магазин ${marketplaceChannel} в разделе «Интеграции».`}</span>
          </div>}
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
              "marketplace-product-report",
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
          ) : page === "marketplace-product-report" ? (
            <Suspense fallback={<Spinner />}><MarketplaceProductReport ctx={ctx} /></Suspense>
          ) : page === "marketplace-returns" ? (
            <Suspense fallback={<Spinner />}><MarketplaceReturns ctx={ctx} /></Suspense>
          ) : page === "stock" ? (
            <Stock ctx={ctx} />
          ) : ["assistant", "content", "designer"].includes(page) ? (
            <AIPage
              key={page}
              page={page}
              ctx={ctx}
              enabled={settings.ai_enabled}
              claudeSkills={settings.claude_skills}
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
              onSkillsUpdated={setSettings}
            />
          ) : page === "expenses" ? (
            <ExpensesPage ctx={ctx}/>
          ) : page === "cash" ? (
            <><div className="panel cash-help"><h2>Что здесь учитывается</h2><p>Cash Flow — это фактические поступления и выплаты за период. Здесь отражаются проведённые денежные операции; прибыль считается отдельно по продажам, себестоимости и расходам.</p></div><DataPage key={page} page={page} ctx={ctx}/></>
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

function ExpenseSummary({ ctx, channelFilter, setChannelFilter }) {
  const params = new URLSearchParams({start:ctx.start, end:ctx.end});
  if (ctx.company) params.set("company_id", ctx.company);
  const {data, error, loading} = useLoad(`/expenses/summary?${params}`, ctx.refresh);
  if (loading) return <section className="panel expense-summary"><Spinner/></section>;
  if (error) return <section className="panel expense-summary"><ErrorBox error={error}/></section>;
  const summary = data || {};
  const channels = Array.isArray(summary.channels) ? summary.channels : [];
  const channelOptions = [...new Map(channels.map((row) => [row.channel, row.channel_label || row.channel])).entries()];
  const activeFilter = channelFilter !== "all" && !channelOptions.some(([key]) => key === channelFilter) ? "all" : channelFilter;
  const selectedChannels = activeFilter === "all" ? channels : channels.filter((row) => row.channel === activeFilter);
  const total = activeFilter === "all" ? Number(summary.total || 0) : selectedChannels.reduce((sum, row) => sum + Number(row.total || 0), 0);
  const posted = activeFilter === "all" ? Number(summary.posted_total || 0) : selectedChannels.reduce((sum, row) => sum + Number(row.posted_total || 0), 0);
  const estimated = activeFilter === "all" ? Number(summary.commission_estimated || 0) : selectedChannels.reduce((sum, row) => sum + Number(row.estimated_total || 0), 0);
  const details = selectedChannels.flatMap((row) => {
    const breakdown = row.category_breakdown || Object.fromEntries(
      Object.entries(row.categories || {}).map(([category, amount]) => [category, {posted_total: amount, estimated_total: 0, total: amount}]),
    );
    return Object.entries(breakdown).map(([category, values]) => ({
      channel: row.channel_label || row.channel,
      account: row.account_name || "—",
      category,
      posted_total: Number(values.posted_total || 0),
      estimated_total: Number(values.estimated_total || 0),
      total: Number(values.total ?? (Number(values.posted_total || 0) + Number(values.estimated_total || 0))),
    }));
  });
  const kpis = [
    [activeFilter === "all" ? "Всего с расчётными комиссиями" : `Всего · ${channelOptions.find(([key]) => key === activeFilter)?.[1] || activeFilter}`, total],
    ["Проведено в учёте", posted],
    ["Расчётная комиссия / оценка", estimated],
    [activeFilter === "all" ? "Записей" : "Магазинов", activeFilter === "all" ? Number(summary.records || 0) : selectedChannels.length],
  ];
  return <section className="panel expense-summary" aria-label="Расходы по источникам и категориям">
    <div className="panel-heading"><div><h2>Расходы за период</h2><p className="muted">{ctx.start} — {ctx.end} · маркетплейсы, офлайн и B2B</p></div></div>
    <div className="secondary-kpis compact-kpis">
      {kpis.map(([label, amount]) => <div key={label}><span>{label}</span><strong>{typeof amount === "number" && label !== "Записей" && label !== "Магазинов" ? money(amount) : amount}</strong></div>)}
    </div>
    {summary.commission_estimate_warning && <p className="panel-note amber">Есть фактические комиссии Kaspi. Расчёт по ставке не добавлен, чтобы не задвоить расходы.</p>}
    <div className="expense-channel-selector" role="group" aria-label="Фильтр расходов по маркетплейсу">
      <button type="button" className={activeFilter === "all" ? "active" : ""} aria-pressed={activeFilter === "all"} onClick={() => setChannelFilter("all")}>Все каналы</button>
      {channelOptions.map(([key, label]) => <button key={key} type="button" className={activeFilter === key ? "active" : ""} aria-pressed={activeFilter === key} onClick={() => setChannelFilter(key)}>{label}</button>)}
    </div>
    <div className="expense-breakdown-panel">
      <h3>{activeFilter === "all" ? "Расходы по магазинам и статьям" : `Расходы · ${channelOptions.find(([key]) => key === activeFilter)?.[1] || activeFilter}`}</h3>
      {details.length ? <>
        <div className="expense-breakdown-desktop">
          <table>
            <thead><tr><th>Канал</th><th>Магазин</th><th>Статья расхода</th><th>Проведено</th><th>Расчётная оценка</th><th>Всего</th></tr></thead>
            <tbody>{details.map((row, index) => <tr key={`${row.channel}-${row.account}-${row.category}-${index}`}>
              <td>{row.channel}</td><td>{row.account}</td><td className="strong">{row.category}</td>
              <td>{money(row.posted_total)}</td><td>{money(row.estimated_total)}</td><td className="strong">{money(row.total)}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="expense-breakdown-mobile">
          {selectedChannels.map((channel) => {
            const breakdown = channel.category_breakdown || Object.fromEntries(Object.entries(channel.categories || {}).map(([category, amount]) => [category, {posted_total: amount, estimated_total: 0, total: amount}]));
            const rows = Object.entries(breakdown);
            return <article className="expense-market-card" key={`${channel.channel}-${channel.account_id || channel.account_name}`}>
              <header><div><strong>{channel.channel_label || channel.channel}</strong><span>{channel.account_name || "—"}</span></div><b>{money(channel.total || 0)}</b></header>
              <div className="expense-market-card-totals"><span>Проведено<strong>{money(channel.posted_total || 0)}</strong></span><span>Расчётное<strong>{money(channel.estimated_total || 0)}</strong></span></div>
              <div className="expense-market-categories">{rows.map(([category, values]) => <div className="expense-market-category" key={category}>
                <strong>{category}</strong><span>Проведено <b>{money(values.posted_total || 0)}</b></span>
                {Number(values.estimated_total || 0) > 0 && <span>Расчётное <b>{money(values.estimated_total)}</b></span>}
                <span>Всего <b>{money(values.total ?? (Number(values.posted_total || 0) + Number(values.estimated_total || 0)))}</b></span>
              </div>)}</div>
            </article>;
          })}
        </div>
      </> : <Empty text="За выбранный период расходов по этому каналу нет."/>}
    </div>
    <p className="panel-note">Проведено — подтверждённые операции из учёта. Расчётная комиссия показана отдельно и не является фактическим удержанием или выплатой.</p>
  </section>;
}
function ExpenseOperations({ ctx, channelFilter }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const pageSize = 200;

  const buildPath = useCallback((offset = 0) => {
    const params = new URLSearchParams({start:ctx.start, end:ctx.end, limit:String(pageSize), offset:String(offset)});
    if (ctx.company) params.set("company_id", ctx.company);
    if (channelFilter !== "all") params.set("channel", channelFilter);
    return "/expenses/operations?" + params.toString();
  }, [ctx.start, ctx.end, ctx.company, channelFilter]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    setItems([]);
    setTotal(0);
    api(buildPath(0)).then((data) => {
      if (!alive) return;
      setItems(data.items || []);
      setTotal(Number(data.total || 0));
    }).catch((e) => {
      if (alive) setError(e.message || "Не удалось загрузить список расходов");
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => { alive = false; };
  }, [buildPath, ctx.refresh]);

  const loadMore = async () => {
    if (loadingMore || items.length >= total) return;
    setLoadingMore(true);
    setError("");
    try {
      const data = await api(buildPath(items.length));
      setItems((current) => [...current, ...(data.items || [])]);
    } catch (e) {
      setError(e.message || "Не удалось загрузить следующие расходы");
    } finally {
      setLoadingMore(false);
    }
  };
  const categories = [...new Set(items.map((row) => row.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"ru"));
  const normalizedSearch = search.trim().toLocaleLowerCase("ru");
  const visible = items.filter((row) => {
    if (category !== "all" && row.category !== category) return false;
    if (!normalizedSearch) return true;
    return [row.date,row.channel,row.account_name,row.category,row.reference,row.product_name,row.sku,row.product_id,row.record_id,row.description]
      .some((value) => String(value ?? "").toLocaleLowerCase("ru").includes(normalizedSearch));
  });
  const channelLabel = channelFilter === "all" ? "все каналы" : channelFilter;
  return <section className="panel expense-operations" aria-label="Отдельные операции расходов">
    <div className="panel-heading expense-operations-heading">
      <div><h2>Список расходов</h2><p className="muted">Отдельные проведённые операции · {channelLabel} · {ctx.start} — {ctx.end}</p></div>
      <strong className="expense-operation-count">{items.length} из {total}</strong>
    </div>
    <div className="expense-operation-filters">
      <label className="expense-operation-search"><Search size={16}/><input aria-label="Поиск по расходам" value={search} onChange={(e)=>setSearch(e.target.value)} placeholder="Поиск: дата, товар, SKU, ID, документ"/></label>
      <label>Статья расхода<select value={category} onChange={(e)=>setCategory(e.target.value)}><option value="all">Все статьи</option>{categories.map((name)=><option key={name}>{name}</option>)}</select></label>
    </div>
    {error && <ErrorBox error={error}/>}
    {loading ? <Spinner/> : visible.length ? <>
      <div className="expense-operations-desktop">
        <table><thead><tr><th>Дата</th><th>Статья</th><th>Канал / магазин</th><th>Товар / SKU</th><th>ID товара</th><th>ID операции / документ</th><th>Статус</th><th>Сумма</th></tr></thead>
          <tbody>{visible.map((row)=><tr key={row.key}>
            <td>{row.date}</td><td className="strong">{row.category}</td><td>{row.channel}<small className="expense-operation-sub">{row.account_name}</small></td>
            <td>{row.product_name || row.sku ? <>{row.product_name || "Товар"}<small className="expense-operation-sub">{row.sku || "SKU не указан"}</small></> : "—"}</td>
            <td>{row.product_id ?? "—"}</td><td>{row.reference}<small className="expense-operation-sub">ID записи: {row.record_id}</small></td><td><span className="expense-operation-status">{row.status}</span></td><td className="strong expense-operation-amount">{money(row.amount)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="expense-operations-mobile">
        {visible.map((row)=><article className="expense-operation-card" key={row.key}>
          <header><div><strong>{row.category}</strong><span>{row.date} · {row.channel}</span></div><b>{money(row.amount)}</b></header>
          <dl>
            <div><dt>Магазин</dt><dd>{row.account_name}</dd></div>
            <div><dt>Товар</dt><dd>{row.product_name || row.sku || "—"}{row.sku && row.product_name ? <small>SKU: {row.sku}</small> : null}</dd></div>
            <div><dt>ID товара</dt><dd>{row.product_id ?? "—"}</dd></div>
            <div><dt>ID операции / документ</dt><dd>{row.reference}<small>ID записи: {row.record_id}</small></dd></div>
            <div><dt>Статус</dt><dd>{row.status}</dd></div>
          </dl>
        </article>)}
      </div>
    </> : <Empty text={items.length ? "По этому поиску расходов нет." : "За выбранный период проведённых расходов нет."}/>}
    {!loading && items.length < total && <button className="secondary expense-load-more" type="button" disabled={loadingMore} onClick={loadMore}>{loadingMore ? "Загружаем…" : `Показать ещё · осталось ${total - items.length}`}</button>}
    <p className="panel-note">В списке показаны фактические расходы и суммы комиссии, логистики и рекламы, записанные в продажах. Расчётная комиссия Kaspi отображается отдельно выше: у дневной оценки нет отдельного ID операции или товара.</p>
  </section>;
}
function ExpensesPage({ ctx }) {
  const [channelFilter, setChannelFilter] = useState("all");
  return <><ExpenseSummary ctx={ctx} channelFilter={channelFilter} setChannelFilter={setChannelFilter}/><ExpenseOperations ctx={ctx} channelFilter={channelFilter}/><DataPage key="expenses" page="expenses" ctx={ctx}/></>;
}

function ReportPage({ page, ctx }) {
  const [detailMetric, setDetailMetric] = useState(null), [alertRetry, setAlertRetry] = useState(0);
  const [dashboardStalled, setDashboardStalled] = useState(false);
  const usesDashboard = page === "dashboard" || page === "analytics";
  const reportPath = page === "alerts" || page === "forecast" ? null : "/report?start=" + ctx.start + "&end=" + ctx.end +
    (ctx.company ? "&company_id=" + ctx.company : "") +
    (usesDashboard ? "&active_only=true" : "");
  const summaryPath = "/dashboard/summary?start=" + ctx.start + "&end=" + ctx.end +
    (ctx.company ? "&company_id=" + ctx.company : "");
  const marketplaceSummaryPath = (channel) => {
    const params = new URLSearchParams({channel, start:ctx.start, end:ctx.end});
    if (ctx.company) params.set("company_id", ctx.company);
    return "/marketplace-summary?" + params;
  };
  const alertsPath = page === "alerts" ? "/alerts?start=" + ctx.start + "&end=" + ctx.end +
    (ctx.company ? "&company_id=" + ctx.company : "") : null;
  const { data: dash, error: dashError, loading: dashLoading } = useLoad(
    usesDashboard ? summaryPath : null,
    ctx.refresh,
    { cacheScope: ctx.auth.user.id, debounceMs: usesDashboard ? 900 : 0 },
  );
  // Keep the overview lightweight; detailed calculations load only on Analytics.
  const dashboardReportPath = page === "dashboard" ? null : reportPath;
  const { data: loadedReport, error: reportError, loading: reportLoading } = useLoad(
    page === "forecast" ? null : dashboardReportPath,
    ctx.refresh,
    { cacheScope: ctx.auth.user.id, debounceMs: usesDashboard ? 900 : 0 },
  );
  const dashboardKaspiSummary = useLoad(page === "analytics" ? marketplaceSummaryPath("Kaspi") : null, ctx.refresh, {cacheScope:ctx.auth.user.id, debounceMs:900});
  const dashboardWbSummary = useLoad(page === "analytics" ? marketplaceSummaryPath("Wildberries") : null, ctx.refresh, {cacheScope:ctx.auth.user.id, debounceMs:900});
  const { data: systemAlerts, error: systemAlertsError, loading: systemAlertsLoading } = useLoad(alertsPath, `${ctx.refresh}:${alertRetry}`);
  const onNotificationCount = ctx.onNotificationCount;
  useEffect(() => {
    if (page === "alerts" && systemAlerts && !systemAlertsError) {
      onNotificationCount(Math.max(0, Number(systemAlerts.count) || 0));
    }
  }, [onNotificationCount, page, systemAlerts, systemAlertsError]);
  const r = usesDashboard ? (loadedReport || dash?.report) : loadedReport;
  const dashboardChannels = usesDashboard && r ? [
    ...(r.channels || []).filter((row) => !["kaspi", "wb", "wildberries", "каспи", "каспий", "вб", "вайлдберриз"].includes(String(row.name || "").normalize("NFKC").trim().toLocaleLowerCase("ru-RU"))),
    {name:"Kaspi", revenue:dashboardKaspiSummary.data?.api_revenue, returns:dashboardKaspiSummary.data?.api_returns, apiLoading:dashboardKaspiSummary.loading, apiError:dashboardKaspiSummary.error},
    {name:"Wildberries", revenue:dashboardWbSummary.data?.api_revenue, returns:dashboardWbSummary.data?.returns, apiLoading:dashboardWbSummary.loading, apiError:dashboardWbSummary.error},
  ] : (r?.channels || []);
  const dashboardRevenueTotal = dashboardChannels.reduce((total, row) => total + (Number(row.revenue) || 0), 0);
  const dashboardMarketplaceSources = [
    {channel:"Kaspi", state:dashboardKaspiSummary},
    {channel:"Wildberries", state:dashboardWbSummary},
  ];
  useEffect(() => {
    setDashboardStalled(false);
    const waitingForHeadline = usesDashboard && dashLoading && !dash?.report;
    if (!waitingForHeadline) return;
    const timer = window.setTimeout(() => setDashboardStalled(true), 30000);
    return () => window.clearTimeout(timer);
  }, [usesDashboard, dashLoading, dash?.report, ctx.start, ctx.end, ctx.company, ctx.refresh]);
  if (page === "dashboard" && !dash?.report && dashLoading) {
    if (!dashboardStalled) return <Spinner />;
    return <section className="panel dashboard-load-warning" role="status">
      <strong>Краткая сводка загружается дольше обычного</strong>
      <p>Сервер пока не вернул сводку. Можно повторить загрузку; расчёты отчётов не изменялись.</p>
      <button className="secondary" type="button" onClick={() => { setDashboardStalled(false); ctx.reload(); }}>Повторить загрузку</button>
    </section>;
  }
  if (page === "dashboard" && !dash?.report && dashError) return <section className="panel dashboard-load-warning" role="alert"><ErrorBox error={dashError}/><button className="secondary" type="button" onClick={ctx.reload}>Повторить загрузку</button></section>;
  if (page === "dashboard") {
    const fast = dash?.report || {};
    const headline = [
      ["Оборот сегодня", dash?.today?.revenue, "На " + (dash?.as_of || "")],
      ["Прибыль сегодня", dash?.today?.net_profit, "Чистая прибыль"],
      ["Оборот месяца", dash?.month?.revenue, "С начала месяца"],
      ["Валовая прибыль месяца", dash?.month?.gross_profit, "С начала месяца"],
      ["Чистая прибыль месяца", dash?.month?.net_profit, "С начала месяца"],
    ];
    const kpis = [
      ["Выручка за период", fast.revenue, Wallet, "За вычетом возвратов"],
      ["Валовая прибыль", fast.gross_profit, Layers, "Выручка минус себестоимость"],
      ["Чистая прибыль", fast.net_profit, TrendingUp, "После учтённых расходов"],
      ["Продано единиц", fast.units, Package, "Количество по операциям"],
    ];
    const channelColors = { kaspi:"#ed4c4c", wildberries:"#8c38ce", ozon:"#2473dd", offline:"#40856a", b2b:"#d5a426" };
    const quickChannels = (fast.channel_summary || []).map((row) => ({
      ...row,
      channel: row.channel || row.name || "Другие",
      revenue: Number(row.revenue) || 0,
    }));
    const quickChannelTotal = quickChannels.reduce((sum, row) => sum + Math.max(0, row.revenue), 0);
    const marketplaceCards = ["Kaspi", "Wildberries"].map((name) => {
      const row = quickChannels.find((item) => String(item.channel).trim().toLowerCase() === name.toLowerCase());
      return { name, revenue: row?.revenue ?? null, returns: row?.returns ?? null, units: row?.quantity ?? null };
    });
    const chartChannels = quickChannels.filter((row) => row.revenue > 0);
    return (
      <div className="qor-overview qor-overview-quick">
        <div className="qor-quick-headline" aria-label="Ключевые показатели">
          {headline.slice(0, 3).map(([title, value, note], index) => {
            const Icon = [Wallet, CalendarDays, TrendingUp][index];
            return <article className="qor-quick-headline-card" key={title}>
              <i><Icon size={16}/></i><div><small>{title}</small><strong>{value == null ? "—" : money(value)}</strong><span>{note}</span></div>
            </article>;
          })}
        </div>
        <div className="qor-overview-kpis qor-quick-kpis">
          {kpis.map(([title, value, Icon, note], index) => <article className="qor-overview-kpi" key={title}>
            <div className="qor-overview-kpi-top"><span>{title}</span><i className={index === 2 ? "is-profit" : ""}><Icon size={17}/></i></div>
            <strong>{value == null ? "—" : index === 3 ? decimal(value) : money(value)}</strong><small>{note}</small>
          </article>)}
        </div>
        <section className="qor-quick-marketplaces" aria-label="Продажи по маркетплейсам">
          {marketplaceCards.map((row) => {
            const key = row.name.toLowerCase(), color = channelColors[key];
            const share = quickChannelTotal && row.revenue != null ? Math.min(100, Math.max(0, row.revenue / quickChannelTotal * 100)) : 0;
            return <article className={`qor-quick-marketplace qor-quick-marketplace--${key}`} key={row.name}>
              <div className="qor-quick-marketplace-mark">{row.name === "Wildberries" ? "WB" : "K"}</div>
              <div className="qor-quick-marketplace-body"><div><strong>{row.name}</strong><span>{row.units == null ? "Продажи за период" : `${decimal(row.units)} шт. продано`}</span></div>
                <b>{row.revenue == null ? "Нет данных в сводке" : money(row.revenue)}</b>
                <div className="qor-quick-marketplace-track"><i style={{width:`${share}%`,background:color}}/></div>
                <small>{row.returns == null ? "Возвраты: —" : `Возвраты: ${money(row.returns)}`}</small>
              </div>
            </article>;
          })}
        </section>
        <div className="qor-quick-charts">
          <section className="panel qor-quick-channel-chart">
            <div className="panel-heading"><div><h2>Продажи по каналам</h2><span>Доля выручки за выбранный период</span></div><span className="qor-chart-caption">{ctx.start} — {ctx.end}</span></div>
            {chartChannels.length ? <div className="qor-quick-channel-list">{chartChannels.sort((a,b)=>b.revenue-a.revenue).map((row) => {
              const color = channelColors[String(row.channel).toLowerCase()] || "#40856a", share = quickChannelTotal ? row.revenue / quickChannelTotal * 100 : 0;
              return <div className="qor-quick-channel-row" key={row.channel}><div><span><i style={{background:color}}/>{row.channel}</span><b>{money(row.revenue)}</b></div><div className="qor-quick-channel-track"><i style={{width:`${share}%`,background:color}}/></div><small>{decimal(share)}% выручки</small></div>;
            })}</div> : <Empty text="За выбранный период нет продаж по каналам"/>}
          </section>
          <section className="panel qor-quick-share-panel">
            <div className="panel-heading"><div><h2>Структура продаж</h2><span>Распределение по каналам</span></div></div>
            {chartChannels.length ? <>
              <div className="qor-quick-share-chart"><ResponsiveContainer width="100%" height={188}><PieChart>
                <Pie data={chartChannels} dataKey="revenue" nameKey="channel" innerRadius={55} outerRadius={78} paddingAngle={3} stroke="none">
                  {chartChannels.map((row) => <Cell key={row.channel} fill={channelColors[String(row.channel).toLowerCase()] || "#40856a"}/>)}
                </Pie><Tooltip formatter={(value) => money(value)}/>
              </PieChart></ResponsiveContainer></div>
              <p className="qor-quick-share-total">Выручка по каналам <strong>{money(quickChannelTotal)}</strong></p>
            </> : <Empty text="Нет данных для диаграммы"/>}
          </section>
        </div>
        <div className="qor-quick-footer"><div><strong>Нужна подробная аналитика?</strong><span>Отчёт по объединённым SKU открывается отдельной кнопкой сверху.</span></div><button className="secondary" type="button" onClick={() => ctx.navigate("analytics")}>Открыть аналитику <span aria-hidden="true">→</span></button></div>
      </div>
    );
  }
  if ((page === "analytics" || (!usesDashboard && page !== "forecast")) && reportLoading) return <Spinner />;
  if ((page === "analytics" || (!usesDashboard && page !== "forecast")) && reportError) return <section className="panel dashboard-load-warning" role="alert"><ErrorBox error={reportError}/><button className="secondary" type="button" onClick={ctx.reload}>Повторить загрузку</button></section>;
  if (page === "alerts") {
    if (systemAlertsLoading && !systemAlerts) return <div className="panel" role="status"><Spinner/><p>Загружаем проверки рабочего пространства…</p></div>;
    if (systemAlertsError) return <div className="panel"><ErrorBox error={systemAlertsError}/><button className="secondary" onClick={()=>setAlertRetry(value=>value+1)}>Повторить загрузку</button></div>;
    const stockAlerts = Array.isArray(systemAlerts?.stock_alerts) ? systemAlerts.stock_alerts : [];
    const receivables = Array.isArray(systemAlerts?.receivables) ? systemAlerts.receivables : [];
    const systemAlertItems = Array.isArray(systemAlerts?.items) ? systemAlerts.items : [];
    return (
      <>
        <div className="panel">
          <div className="panel-heading">
            <h2>Автоматические проверки ERP</h2>
            <span className="badge amber">{systemAlerts?.count ?? "…"}</span>
          </div>
          {systemAlertItems.length ? <div className="alert-list">{systemAlertItems.map((item, index) =>
              <div className={`alert-item ${item.severity || "info"}`} key={`${item.type}-${item.account_id || "all"}-${index}`}>
                <strong>{item.title}</strong>
                {item.action && <p>{item.action}</p>}
              </div>)}
            </div> : <Empty text="Критических проверок нет." />}
        </div>
        <div className="panel">
          <div className="panel-heading">
            <h2>Остатки требуют внимания</h2>
            <span className="badge amber">{stockAlerts.length} товаров</span>
          </div>
          <Table rows={stockAlerts} cols={columns.stock} />
        </div>
        <div className="panel">
          <div className="panel-heading">
            <h2>Просроченные оплаты</h2>
          </div>
          <Table
            rows={receivables.filter((x) => x.overdue)}
            cols={["reference", "channel", "due", "due_date"]}
            refs={ctx.refs}
          />
        </div>
      </>
    );
  }
  if (page === "forecast") return <Forecast ctx={ctx} />;
  if (page === "profit" || page === "accounting")
    return (
      <>
        <CostPendingNotice report={r} ctx={ctx} />
        {page === "accounting" && <p className="panel-note amber" role="note">
          Бухгалтерский отчёт включает операции отключённых магазинов за выбранный период. Обзор бизнеса показывает только активные магазины; из-за этого выручка и количество продаж без себестоимости могут отличаться.
        </p>}
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
              ["Реклама", …56258 tokens truncated…kdown">{out}</div>}
function AIWorkspace({ ctx, enabled, claudeSkills }) {
  const [agents,setAgents]=useState([]),[threads,setThreads]=useState([]),[thread,setThread]=useState(null),[messages,setMessages]=useState([]);
  const [text,setText]=useState(""),[files,setFiles]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState(""),[actions,setActions]=useState([]),[plans,setPlans]=useState([]),[jobState,setJobState]=useState(null),[accountId,setAccountId]=useState("");
  const agent=thread?.agent||"rick";
  const [historyOpen,setHistoryOpen]=useState(false);
  const messagesEndRef=useRef(null);
  useEffect(()=>{messagesEndRef.current?.scrollIntoView({block:"end",behavior:"smooth"})},[messages,busy,thread]);
  const aiAccounts=(ctx.refs.accounts||[]).filter(a=>a.active!==false&&["Kaspi","Wildberries","Ozon","Offline","B2B"].includes(a.channel)&&(!ctx.company||String(a.company_id)===String(ctx.company)));
  useEffect(()=>{if(accountId&&!(ctx.refs.accounts||[]).some(a=>String(a.id)===String(accountId)&&a.active!==false&&["Kaspi","Wildberries","Ozon","Offline","B2B"].includes(a.channel)&&(!ctx.company||String(a.company_id)===String(ctx.company))))setAccountId("");},[accountId,ctx.company,ctx.refs.accounts]);
  const reloadThreads=()=>api("/ai/threads").then(d=>setThreads(d.items||[]));
  const reloadActions=()=>api("/ai/actions?status=pending").then(d=>setActions(d.items||[]));
  const reloadPlans=()=>api("/ai/plans?status=pending").then(d=>setPlans(d.items||[]));
  useEffect(()=>{api("/ai/agents").then(d=>setAgents(d.items||[])).catch(()=>{});reloadThreads().catch(()=>{});reloadActions().catch(()=>{});reloadPlans().catch(()=>{});},[ctx.refresh]);
  useEffect(()=>{if(!thread)return;api(`/ai/threads/${thread.id}/messages`).then(d=>setMessages(d.items||[])).catch(e=>setError(e.message));},[thread]);
  const newChat=async(a="rick")=>{const t=await api("/ai/threads",{method:"POST",body:{agent:a,company_id:ctx.company?Number(ctx.company):null}});setThread(t);setMessages([]);reloadThreads()};
  const chooseAgent=async(a)=>{if(!thread)return newChat(a);const t=await api(`/ai/threads/${thread.id}`,{method:"PATCH",body:{agent:a}});setThread(t);reloadThreads()};
  const uploadFiles=async(list)=>{if(!ctx.company){setError("Сначала выберите компанию");return}setBusy(true);try{const out=[];for(const file of Array.from(list).slice(0,8)){const fd=new FormData();fd.append("company_id",ctx.company);fd.append("file",file);out.push(await api("/documents/upload",{method:"POST",body:fd}))}setFiles(f=>[...f,...out].slice(0,8))}catch(e){setError(e.message)}finally{setBusy(false)}};
  const send=async(e)=>{e.preventDefault();if((!text.trim()&&!files.length)||busy)return;if(!enabled){setError("Claude API не подключён. Настройте ANTHROPIC_API_KEY на сервере.");return}setError("");setBusy(true);try{let t=thread;if(!t)t=await api("/ai/threads",{method:"POST",body:{agent:"rick",company_id:ctx.company?Number(ctx.company):null}});
    const attachments=files.map(f=>({document_id:f.id,name:f.name,mime:f.mime}));const userMsg=await api(`/ai/threads/${t.id}/messages`,{method:"POST",body:{role:"user",content:text||"Проанализируй вложения",attachments}});
    setThread(t);setMessages(m=>[...m,userMsg]);const history=[...messages.slice(-12),userMsg].map(m=>({role:m.role,content:m.content}));
    let j=await api("/jobs",{method:"POST",body:{kind:"assistant",payload:{question:text||"Проанализируй приложенные материалы",agent:t.agent,company_id:ctx.company?Number(ctx.company):null,account_id:accountId?Number(accountId):null,start:ctx.start,end:ctx.end,thread_id:t.id,history,document_ids:attachments.map(x=>x.document_id)}}});
    setJobState(j);setText("");setFiles([]);
    if(["queued","running"].includes(j.status)) j=await waitForAIJob(j.id,setJobState);
    if(j.status!=="done") throw new Error(j.error||"AI-задание завершилось с ошибкой");
    const answer=j.result?.answer||j.result?.text||j.result?.notice||"Готово";
    const assistantMsg=await api(`/ai/threads/${t.id}/messages`,{method:"POST",body:{role:"assistant",content:answer,meta:{job_id:j.id,agent:j.result?.agent||agent,tools_used:j.result?.tools_used||[]}}});
    setMessages(m=>[...m,assistantMsg]);setJobState(null);reloadThreads();reloadActions();reloadPlans();}catch(e){setError(e.message)}finally{setBusy(false)}};
  const copy=(v)=>navigator.clipboard?.writeText(v);
  const act=async(id,verb)=>{setError("");try{await api(`/ai/actions/${id}/${verb}`,{method:"POST"});await reloadActions();ctx.bump?.()}catch(e){setError(e.message)}};
  const planAct=async(id,verb)=>{setError("");try{await api(`/ai/plans/${id}/${verb}`,{method:"POST"});await Promise.all([reloadPlans(),reloadActions()]);ctx.bump?.()}catch(e){setError(e.message)}};
  return <div className="chat-shell">
    <aside className={`chat-sidebar panel ${historyOpen?"history-open":""}`}><button className="chat-history-close" onClick={()=>setHistoryOpen(false)}><X size={16}/> Закрыть историю</button><button className="primary chat-new" onClick={()=>{newChat(agent);setHistoryOpen(false)}}><Plus size={17}/>Новый чат</button><div className="chat-history"><span className="eyebrow">ИСТОРИЯ</span>{threads.map(t=><button key={t.id} className={`chat-thread ${thread?.id===t.id?"active":""}`} onClick={()=>{setThread(t);setHistoryOpen(false)}}><MessageSquare size={15}/><span><b>{t.title}</b><small>{agents.find(a=>a.id===t.agent)?.name||t.agent}</small></span></button>)}</div></aside>
    <section className="chat-main panel"><header className="chat-head"><div className="chat-title"><button className="chat-history-toggle" onClick={()=>setHistoryOpen(v=>!v)} aria-expanded={historyOpen}><MessageSquare size={16}/> История</button><div><span className="eyebrow">QOR AI · КОМАНДА БИЗНЕСА</span><h2>{agents.find(a=>a.id===agent)?.name||"Арман"} · {AI_ROLE_TITLES[agent]||agents.find(a=>a.id===agent)?.title||"AI-руководитель"}</h2></div></div><div className="chat-head-controls"><select aria-label="Магазины для анализа AI" value={accountId} onChange={e=>setAccountId(e.target.value)}><option value="">Все магазины выбранной компании</option>{aiAccounts.map(a=><option key={a.id} value={a.id}>{a.channel} · {a.name}</option>)}</select><select aria-label="AI-специалист" value={agent} onChange={e=>chooseAgent(e.target.value)}>{agents.map(a=><option key={a.id} value={a.id}>{a.name} — {AI_ROLE_TITLES[a.id]||a.title}</option>)}</select></div></header>
      {!enabled&&<div className="info-banner">Для живых ответов подключите ANTHROPIC_API_KEY на сервере.</div>}
      {enabled&&<div className="chat-skill-status">Навыки Claude: {claudeSkills?.enabled?`${claudeSkills.configured}/${claudeSkills.required} подключено`:`не подключены · ${claudeSkills?.configured||0}/${claudeSkills?.required||11}`}</div>}
      {(actions.length>0||plans.length>0)&&<div className="ai-approval-summary"><ShieldCheck size={17}/><span><b>{actions.length+plans.length} ожидают решения</b><small>AI подготовил изменения; проверьте и подтвердите их ниже.</small></span></div>}
      {jobState&&["queued","running"].includes(jobState.status)&&<div className="info-banner">Задание #{jobState.id} выполняется в фоне. Страница остаётся доступной.</div>}<div className="chat-messages">{!messages.length&&<div className="chat-empty ai-control-center"><div className="ai-welcome"><div className="ai-orb"><Sparkles size={28}/></div><div><span className="eyebrow">QOR AI · КОМАНДА БИЗНЕСА</span><h2>Управляйте бизнесом через один чат</h2><p>Финансы, продажи, товары и маркетплейсы. AI готовит анализ и действия на основе данных ERP; изменения проходят проверку и ваше подтверждение.</p></div></div><div className="ai-workflows"><button className="ai-workflow-card" onClick={()=>setText("Подготовь ежедневный отчёт руководителю: продажи, прибыль, выплаты, изменения по Kaspi и Wildberries, проблемы и что требует моего решения. Используй текущий выбранный период и укажи, если данных не хватает.")}><span className="ai-workflow-icon"><TrendingUp size={19}/></span><b>Отчёт руководителю</b><small>Продажи, прибыль, каналы и важные отклонения</small><em>Подготовить →</em></button><button className="ai-workflow-card" onClick={()=>setText("Проверь товары и остатки: что быстро продаётся, что заканчивается, что продаётся медленно. Дай приоритетный список и объясни выводы только по подтверждённым данным QOR.")}><span className="ai-workflow-icon"><Package size={19}/></span><b>Контроль товаров</b><small>Остатки, темп продаж и товары для внимания</small><em>Проверить →</em></button><button className="ai-workflow-card" onClick={()=>setText("Проанализируй закупки по каждому SKU отдельно для Kaspi и Wildberries: сколько реально продано за выбранный период, какой подтверждённый остаток сейчас, какой темп продаж и стоит ли пополнить. Назови причины рекомендации и отдельно перечисли товары, которые не стоит закупать. Если данные ERP не связывают SKU с конкретным каналом или не подтверждают остаток, напиши «Не подтверждено» и не угадывай количество.")}><span className="ai-workflow-icon"><Package size={19}/></span><b>Что закупить?</b><small>Рекомендации по Kaspi и Wildberries с объяснением</small><em>Получить список →</em></button><button className="ai-workflow-card" onClick={()=>setText("Сверь продажи Kaspi и Wildberries за выбранный период. Покажи показатели каждого канала отдельно, найденные расхождения и ограничения данных. Не меняй отчёты и не пересчитывай финансовые показатели.")}><span className="ai-workflow-icon"><ShieldCheck size={19}/></span><b>Проверка каналов</b><small>Kaspi и Wildberries по данным ERP</small><em>Сверить →</em></button><button className="ai-workflow-card" onClick={()=>setText("Подготовь финансовую сводку за выбранный период для бухгалтера: выручка, расходы, прибыль, деньги и выплаты, расшифровки по каналам и список недостающих данных. Ничего не проводи автоматически.")}><span className="ai-workflow-icon"><FileText size={19}/></span><b>Сводка бухгалтеру</b><small>Проверяемые цифры и пояснения</small><em>Подготовить →</em></button><button className="ai-workflow-card" onClick={()=>setText("Помоги сопоставить товары QOR с карточками Kaspi и Wildberries по артикулу, SKU и штрихкоду. Покажи только точные и неоднозначные совпадения отдельно; не создавай автоматические связи без подтверждения.")}><span className="ai-workflow-icon"><Sparkles size={19}/></span><b>Сопоставить карточки</b><small>Поиск общих SKU между площадками</small><em>Начать →</em></button><button className="ai-workflow-card" onClick={()=>setText("У меня новый товар. Помоги подготовить карточку товара QOR: приложу фото и характеристики. Сначала извлеки только видимые/указанные сведения, отметь неизвестное и подготовь черновик для моей проверки.")}><span className="ai-workflow-icon"><ImageIcon size={19}/></span><b>Новый товар по фото</b><small>Черновик из изображения и характеристик</small><em>Подготовить →</em></button></div><div className="ai-control-footer"><span><b>{agents.length||6} AI-специалистов</b><small>Руководитель · финансы · аналитика · товары · маркетинг · контент</small></span><a className="secondary" href={`/api/reports/executive.xlsx?start=${ctx.start}&end=${ctx.end}${ctx.company?`&company_id=${ctx.company}`:""}${accountId?`&account_id=${accountId}`:""}`}><Download size={16}/>Отчёт Excel</a></div></div>}
        {messages.map(m=><div key={m.id} className={`chat-row ${m.role}`}><div className="chat-bubble"><div className="chat-role">{m.role==="user"?"Вы":agents.find(a=>a.id===(m.meta?.agent||agent))?.name||"QOR AI"}</div><div className="chat-text">{m.role==="assistant"?formatAIMessage(m.content):m.content}</div>{m.attachments?.length>0&&<div className="chat-attachments">{m.attachments.map((a,i)=><a key={i} href={`/api/documents/${a.document_id}/download`} target="_blank" rel="noreferrer"><ImageIcon size={15}/>{a.name}</a>)}</div>}{m.role==="assistant"&&<div className="chat-actions"><button onClick={()=>copy(m.content)}><Copy size={14}/>Копировать</button><button onClick={()=>setText("Переделай предыдущий ответ. ")}><RotateCcw size={14}/>Переделать</button></div>}</div></div>)}
        {plans.filter(p=>!thread||!p.thread_id||p.thread_id===thread.id).map(p=><div key={`plan-${p.id}`} className="chat-row assistant"><div className="chat-bubble ai-approval ai-plan"><div className="chat-role">ПЛАН РИКА · НУЖНО ПОДТВЕРЖДЕНИЕ</div><b>{p.title}</b><div className="chat-text">{p.goal}</div><div className="plan-steps">{(p.steps||[]).map((x,i)=><div key={i}><span>{i+1}</span><div><b>{x.title||x.action_type}</b><small>{x.action_type}</small></div></div>)}</div><div className="chat-actions"><button className="primary" onClick={()=>planAct(p.id,"confirm")}>Подтвердить весь план</button><button onClick={()=>planAct(p.id,"cancel")}>Отмена</button></div><small>Каждый шаг повторно проверяет права и записывается в Audit Log. При ошибке выполнение останавливается.</small></div></div>)}
        {actions.filter(a=>!thread||!a.thread_id||a.thread_id===thread.id).map(a=><div key={`action-${a.id}`} className="chat-row assistant"><div className="chat-bubble ai-approval"><div className="chat-role">Требуется подтверждение</div><b>{a.preview?.title||a.action_type}</b><div className="chat-text">{a.preview?.warning}</div><pre>{JSON.stringify(a.preview?.payload||{},null,2)}</pre><div className="chat-actions"><button className="primary" onClick={()=>act(a.id,"confirm")}>Подтвердить</button><button onClick={()=>act(a.id,"cancel")}>Отмена</button></div></div></div>)}
        {busy&&<div className="chat-row assistant"><div className="chat-bubble typing"><Spinner/><span>{agents.find(a=>a.id===agent)?.name||"AI"} работает…</span></div></div>}<div ref={messagesEndRef}/></div>
      <ErrorBox error={error}/><form className="chat-composer" onSubmit={send}>{files.length>0&&<div className="composer-files">{files.map(f=><span key={f.id}>{f.name}<button type="button" onClick={()=>setFiles(x=>x.filter(y=>y.id!==f.id))}>×</button></span>)}</div>}<div className="composer-row"><label className="attach-btn" title="Фото или файл"><Paperclip size={20}/><input type="file" multiple accept="image/*,.pdf,.csv,.xlsx" onChange={e=>uploadFiles(e.target.files)}/></label><textarea rows="1" value={text} onChange={e=>setText(e.target.value)} placeholder="Сообщение QOR AI…" onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send(e)}}}/><button className="send-btn" disabled={!enabled||busy||(!text.trim()&&!files.length)}><Send size={19}/></button></div><small>AI использует только разрешённые данные ERP. Финансовые цифры рассчитывает backend.</small></form>
    </section>
    <aside className="chat-agents panel"><span className="eyebrow">AI-КОМАНДА</span>{agents.map(a=><button key={a.id} className={`agent-mini ${agent===a.id?"active":""}`} onClick={()=>chooseAgent(a.id)}><span>{a.name.slice(0,1)}</span><div><b>{a.name}</b><small>{AI_ROLE_TITLES[a.id]||a.title}</small></div></button>)}</aside>
  </div>
}

function AIPage({ page, ctx, enabled, claudeSkills }) {
  const [text, setText] = useState(""),
    [doc, setDoc] = useState(""),
    [job, setJob] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
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
  if (page === "assistant") return <AIWorkspace ctx={ctx} enabled={enabled} claudeSkills={claudeSkills}/>;
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
                ? (agents.find((a) => a.id === agent)?.name || "Арман") + " · " + (agents.find((a) => a.id === agent)?.title || "AI-руководитель")
                : page === "content"
                  ? "Карточка из фактов о товаре"
                  : "Новая визуальная идея"}
            </h2>
            <p>
              {page === "assistant"
                ? (agent === "rick" ? "Главная точка общения: Арман помогает владельцу увидеть картину бизнеса и выбрать действие." : "Специализированный AI работает только в своей зоне и использует проверенные данные ERP.")
                : page === "content"
                  ? "Укажите характеристики поставщика и выберите загруженное фото."
                  : "Опишите композицию, фон и настроение изображения."}
            </p>
          </div>
        </div>
        {!enabled && (
          <div className="info-banner">
            Claude API пока не подключён. Укажите ANTHROPIC_API_KEY на сервере.
            Финансовая аналитика и калькулятор работают без ключа.
          </div>
        )}
        {page === "assistant" && (
          <div className="ai-team">
            <div className="ai-team-head"><span className="eyebrow">AI-КОМАНДА</span><strong>Выберите специалиста или пишите Арману</strong></div>
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
  const orderCol = find(["номер заказа","№ заказа","код заказа","id заказа","order id","order_id","заказ"]);
  const statusCol = find(["статус заказа","статус","состояние заказа","order status"]);
  const operationCol = find(["тип операции","операция","вид операции","тип транзакции","operation","transaction type"]);
  const skuCol = find(["артикул продавца","артикул","sku","vendor code","код товара"]);
  const lineCol = find(["id позиции","код позиции","номер позиции","order entry id","entry id","line id"]);
  const returnDateCol = find(["дата возврата","дата возврата средств","дата возврата товара","return date","refund date"]);
  const dateCol = find(["дата выдачи","дата продажи","дата завершения заказа","дата завершения","дата операции","sale date","completion date","дата заказа","дата","order date"]);
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
      __qor_refund: refundCol ? Math.abs(numeric(row[refundCol])) : null,
      __qor_sale_reference: "Kaspi:" + accountId + ":" + lineId,
    };
    const cancelled = /(отмен|cancel|cancell)/.test(status);
    const returned = /(возврат|вернул|return|refund)/.test(status);
    const completed = /(выдан|заверш|получен|completed|delivered|продаж|sale)/.test(status);
    const isSaleReportRow = !statusCol && !operationCol;
    if (cancelled) {
      out.push({...base,__qor_event_type:"order",__qor_external_id:lineId});
    } else if (returned) {
      out.push({...base,__qor_date:returnDateCol ? (row[returnDateCol] || "") : "",__qor_event_type:"return",__qor_external_id:lineId+":return"});
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
      out.push({...base,__qor_event_type:returned?"return_logistics":"logistics",__qor_external_id:(returned?"return-delivery:":"delivery:")+id,__qor_amount:sellerDelivery});
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
          order_id:"__qor_order_id", sku:"__qor_sku", quantity:"__qor_quantity", unit_price:"__qor_unit_price",
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
function Settings({ settings, ctx, onLogout, onSkillsUpdated }) {
  const [name, setName] = useState(settings.business_name || ""),
    [old, setOld] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState("");
  const [installingSkills, setInstallingSkills] = useState(false),
    [skillInstallResult, setSkillInstallResult] = useState(null);
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
  const installSkills = async () => {
    setInstallingSkills(true);
    setError("");
    try {
      const result = await api("/ai/skills/install", { method: "POST" });
      setSkillInstallResult(result.skills);
      const updated = await api("/settings");
      onSkillsUpdated?.(updated);
      ctx.notify(`Загружено Skills: ${result.configured}/${result.required}. Сохраните JSON в настройках Render, чтобы включить их в Claude.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setInstallingSkills(false);
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
          Claude API: {settings.ai_enabled ? "подключён" : "ожидает ANTHROPIC_API_KEY"}. Skills: {settings.claude_skills?.enabled ? `${settings.claude_skills.configured}/${settings.claude_skills.required} подключены` : `не подключены (${settings.claude_skills?.configured || 0}/${settings.claude_skills?.required || 11})`}.
          Ключи хранятся на сервере, не в браузере.
        </p>
        <ErrorBox error={error} />
      </form>
      {settings.ai_enabled && !settings.claude_skills?.enabled && can(ctx.auth, "settings", true) && <section className="panel padded wide">
        <h2>Claude Skills · команда QOR</h2>
        <p className="muted">Загрузит 11 подготовленных Skills в тот же Anthropic API workspace, к которому подключён серверный ключ. Ключ остаётся на сервере.</p>
        <button className="primary" type="button" onClick={installSkills} disabled={installingSkills}>{installingSkills ? "Загружаем в Anthropic…" : "Загрузить 11 Skills в Claude API"}</button>
        {skillInstallResult && <label>Конфигурация для Render · QOR_CLAUDE_SKILLS_JSON<textarea readOnly rows={10} value={JSON.stringify(skillInstallResult, null, 2)} /></label>}
      </section>}
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
