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
              отражается в разделе «Деньги и выплаты» отдельно от прибыли.
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
            <div><h2>Деньги: поступления и выплаты</h2><span>Фактическое движение средств за выбранный период</span></div>
          </div>
          <p className="panel-note cashflow-explainer">Это не прибыль: прибыль учитывает продажи, себестоимость и расходы. Здесь показаны деньги, которые фактически поступили или были выплачены, и их остаток.</p>
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
            <h2>Деньги к получению</h2>
          </div>
          <p className="panel-note">Это суммы, которые покупатели или маркетплейсы ещё должны перечислить вашей компании. Это не ваш долг. Сверяйте документ, канал и срок оплаты.</p>
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
  if (page === "dashboard") {
    const overviewCards = [
      ["Выручка", r.revenue, Wallet, "За вычетом возвратов"],
      ["Валовая прибыль", r.gross_profit, Layers, "Выручка − себестоимость"],
      ["Чистая прибыль", r.net_profit, TrendingUp, "После учтённых расходов"],
      ["Выплаты получено", r.cash_inflow, Receipt, "Фактические поступления"],
    ];
    const marketplaceColors = {kaspi:"#ed4c4c", wildberries:"#8c38ce", ozon:"#2473dd", offline:"#40856a", b2b:"#d5a426"};
    const marketplaceColor = (name) => marketplaceColors[String(name || "").toLowerCase()] || "#789187";
    const marketplaceRows = ["Kaspi", "Wildberries", "Ozon"].map((channel) => {
      const related = dashboardChannels.filter((row) => String(row.name || "").split("·")[0].trim().toLowerCase() === channel.toLowerCase());
      const direct = related.find((row) => String(row.name || "").trim().toLowerCase() === channel.toLowerCase());
      const detailRows = related.filter((row) => row !== direct);
      const selected = direct?.revenue != null ? [direct] : detailRows.length ? detailRows : related;
      const revenueRows = selected.filter((row) => row.revenue != null);
      const returnRows = selected.filter((row) => row.returns != null);
      return {
        name: channel,
        revenue: revenueRows.length ? revenueRows.reduce((sum, row) => sum + (Number(row.revenue) || 0), 0) : null,
        returns: returnRows.length ? returnRows.reduce((sum, row) => sum + (Number(row.returns) || 0), 0) : null,
        apiLoading: selected.some((row) => row.apiLoading),
      };
    });
    const marketplaceChartRows = marketplaceRows.map((row) => ({...row, chartRevenue:Math.max(0, Number(row.revenue) || 0)})).filter((row) => row.chartRevenue > 0);
    const marketplaceShareBase = marketplaceChartRows.reduce((sum, row) => sum + row.chartRevenue, 0);
    const topProducts = [...(r.products || [])].sort((a,b)=>(Number(b.revenue)||0)-(Number(a.revenue)||0)).slice(0,5);
    const stockAlerts = (r.stock_alerts || []).slice(0,6);
    return <div className="qor-overview">
      <CostPendingNotice report={r} ctx={ctx}/>
      <div className="qor-overview-kpis">
        {overviewCards.map(([label,value,Icon,note])=><article className="qor-overview-kpi" key={label}>
          <div className="qor-overview-kpi-top"><span>{label}</span><i><Icon size={18}/></i></div>
          <strong>{value == null ? "—" : money(value)}</strong><small>{note}</small>
        </article>)}
      </div>
      <section className="qor-marketplace-cards" aria-label="Продажи по маркетплейсам">
        {marketplaceRows.map((row) => <article className="qor-marketplace-summary-card" key={row.name} style={{"--market-color":marketplaceColor(row.name)}}>
          <div className="qor-marketplace-summary-top"><span className="qor-marketplace-mark">{String(row.name).toLowerCase()==="wildberries"?"WB":String(row.name).slice(0,2).toUpperCase()}</span><b>{row.name}</b></div>
          <strong>{row.revenue == null ? (row.apiLoading ? "Загрузка…" : "—") : money(row.revenue)}</strong>
          <small>{row.returns == null ? "Продажи за выбранный период" : `Возвраты · ${money(row.returns)}`}</small>
          <div className="qor-marketplace-track"><i style={{width:`${Math.max(2,Math.min(100,(Number(row.revenue)||0)/Math.max(marketplaceShareBase,1)*100))}%`}}/></div>
        </article>)}
      </section>
      <div className="qor-overview-main-grid">
        <section className="panel qor-overview-chart">
          <div className="panel-heading"><div><h2>Продажи и прибыль</h2><span>{ctx.start} — {ctx.end}</span></div><div className="qor-chart-legend"><span><i/> Выручка</span><span><i/> Прибыль</span></div></div>
          {r.daily?.length ? <ResponsiveContainer width="100%" height={270}><AreaChart data={r.daily} margin={{top:12,right:10,left:0,bottom:0}}>
            <defs><linearGradient id="qorRevenueFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#0f7653" stopOpacity={.2}/><stop offset="100%" stopColor="#0f7653" stopOpacity={0}/></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#e8eeeb"/><XAxis dataKey="date" tickFormatter={s=>s.slice(8)+"."+s.slice(5,7)} axisLine={false} tickLine={false} minTickGap={24}/><YAxis tickFormatter={n=>decimal(n/100000)+"к"} axisLine={false} tickLine={false} width={52}/><Tooltip formatter={money} labelFormatter={s=>"Дата: "+s}/>
            <Area type="monotone" dataKey="revenue" name="Выручка" stroke="#08734f" strokeWidth={2.5} fill="url(#qorRevenueFill)"/><Area type="monotone" dataKey="profit" name="Прибыль" stroke="#9bc9a9" strokeWidth={2} fill="transparent"/>
          </AreaChart></ResponsiveContainer> : <Empty text="За выбранный период нет операций"/>}
        </section>
        <section className="panel qor-marketplace-panel">
          <div className="panel-heading"><div><h2>Доля по маркетплейсам</h2><span>Распределение выручки за период</span></div></div>
          {marketplaceChartRows.length ? <>
            <div className="qor-share-chart"><ResponsiveContainer width="100%" height={190}><PieChart>
              <Pie data={marketplaceChartRows} dataKey="chartRevenue" nameKey="name" innerRadius={54} outerRadius={78} paddingAngle={3} stroke="none">
                {marketplaceChartRows.map((row) => <Cell key={row.name} fill={marketplaceColor(row.name)}/>) }
              </Pie>
              <Tooltip formatter={money}/>
            </PieChart></ResponsiveContainer></div>
            <div className="qor-share-legend">{marketplaceChartRows.map((row) => <div key={row.name}><span><i style={{background:marketplaceColor(row.name)}}/>{row.name}</span><b>{marketplaceShareBase ? decimal(row.chartRevenue / marketplaceShareBase * 100) : "0"}%</b><strong>{money(row.chartRevenue)}</strong></div>)}</div>
          </> : <Empty text="Нет данных о продажах по маркетплейсам"/>}
          <a className="text-button qor-marketplace-link" href="#analytics">Открыть аналитику <span>→</span></a>
        </section>
      </div>
      <div className="qor-overview-bottom-grid">
        <section className="panel"><div className="panel-heading"><div><h2>Топ товаров</h2><span>По выручке за период</span></div><button className="text-button" onClick={()=>ctx.navigate("products")}>Все товары →</button></div>
          <div className="table-scroll"><table className="qor-overview-table"><thead><tr><th>Товар</th><th>Продажи, шт.</th><th>Выручка</th><th>Валовая прибыль</th></tr></thead><tbody>{topProducts.map((product,index)=><tr key={product.id || product.name || index}><td><b>{product.name || "Товар"}</b><small>{product.sku || "SKU не указан"}</small></td><td>{product.quantity ?? product.units ?? "—"}</td><td>{money(product.revenue)}</td><td>{product.gross_profit == null ? "—" : money(product.gross_profit)}</td></tr>)}</tbody></table></div>
        </section>
        <section className="panel"><div className="panel-heading"><div><h2>Низкий остаток</h2><span>{(r.stock_alerts || []).length} товаров требуют внимания</span></div><button className="text-button" onClick={()=>ctx.navigate("stock")}>Единый склад →</button></div>
          <div className="qor-low-stock-list">{stockAlerts.map((item,index)=><article key={item.id || item.sku || index}><span className="qor-stock-icon"><Package size={16}/></span><div><b>{item.name || item.product_name || "Товар"}</b><small>SKU · {item.sku || "—"}</small></div><strong className="qor-stock-amount">{item.quantity ?? item.stock ?? 0} шт.</strong></article>)}</div>
          {!stockAlerts.length && <Empty text="Нет товаров ниже минимального остатка"/>}
        </section>
      </div>
      <section className="qor-sync-strip" aria-label="Сводки маркетплейсов">
        {dashboardMarketplaceSources.map(({channel,state})=><article className="qor-sync-card" key={channel}><span className="qor-sync-indicator" data-state={state.error ? "error" : state.loading ? "loading" : "ready"}/><div><b>{channel}</b><small>{state.error ? "Ошибка загрузки" : state.loading ? "Синхронизация…" : `Обновлено · ${state.data?.last_sync ? new Date(state.data.last_sync).toLocaleString("ru-RU") : "данные доступны"}`}</small></div><span className="qor-sync-value">{state.data?.api_revenue == null ? "—" : money(state.data.api_revenue)}</span></article>)}
      </section>
      {detailMetric && <ReportDetails ctx={ctx} detail={detailMetric} onClose={()=>setDetailMetric(null)} activeOnly/>}
      <p className="method">{r.method}. {r.scope_note}.</p>
    </div>;
  }
  const headline = [
    ["Оборот сегодня", dash?.today?.revenue, "На " + (dash?.as_of || "—")],
    ["Прибыль сегодня", dash?.today?.net_profit, "Чистая прибыль"],
    ["Оборот месяца", dash?.month?.revenue, "С начала месяца"],
    ["Валовая прибыль месяца", dash?.month?.gross_profit, "С начала месяца"],
    ["Чистая прибыль месяца", dash?.month?.net_profit, "С начала месяца"],
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
      <p className="panel-note amber" role="note">
        Обзор бизнеса показывает только активные магазины. Бухгалтерский отчёт также включает операции отключённых магазинов за выбранный период; до выбора одинакового состава магазинов итоги между экранами не сверены.
      </p>
      {!dash && (
        <p className="panel-note amber" role="status">
          {dashError ? "Краткая сводка не загрузилась. Основной отчёт доступен ниже." : "Загружается краткая сводка…"}
        </p>
      )}
      <div className="dashboard-headline">
        {headline.map(([title, value, note]) => (
          <div className="headline-card" key={title}><span>{title}</span><strong>{value == null ? "—" : money(value)}</strong><small>{note}</small></div>
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
            <small>{note}</small>
          </div>
        ))}
      </div>
      <div className="charts-grid">
        <div className="panel chart-panel">
          <div className="panel-heading">
            <div>
              <h2>Динамика бизнеса</h2>
              <span>Выручка и чистая прибыль</span>
            </div>
            <div className="legend">
              <span>● Выручка</span>
              <span>● Прибыль</span>
            </div>
          </div>
          {r.daily.length ? (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart
                data={r.daily}
                margin={{ top: 15, right: 12, left: 0, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#218a70" stopOpacity={0.18} />
                    <stop offset="100%" stopColor="#218a70" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 5"
                  vertical={false}
                  stroke="#e8eeeb"
                />
                <XAxis
                  dataKey="date"
                  tickFormatter={(s) => s.slice(8) + "." + s.slice(5, 7)}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={24}
                />
                <YAxis
                  tickFormatter={(n) => decimal(n / 100000) + "к"}
                  axisLine={false}
                  tickLine={false}
                  width={54}
                />
                <Tooltip
                  formatter={money}
                  labelFormatter={(s) => "Дата: " + s}
                />
                <Area
                  type="monotone"
                  dataKey="revenue"
                  name="Выручка"
                  stroke="#218a70"
                  strokeWidth={2.5}
                  fill="url(#rev)"
                />
                <Area
                  type="monotone"
                  dataKey="profit"
                  name="Прибыль"
                  stroke="#96ada4"
                  strokeWidth={2}
                  fill="transparent"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <Empty text="За выбранный период нет операций" />
          )}
        </div>
        <div className="panel channel-panel">
          <div className="panel-heading">
            <div>
              <h2>Продажи по аккаунтам</h2>
              <span>Kaspi и Wildberries — API-итоги как на их страницах; остальные каналы — проведённые ERP-операции</span>
            </div>
            <span className="pill">{dashboardChannels.length} каналов</span>
          </div>
          {dashboardChannels.length ? (
            dashboardChannels
              .sort((a, b) => (Number(b.revenue) || 0) - (Number(a.revenue) || 0))
              .slice(0, 7)
              .map((c, i) => (
                <div className="channel" key={c.name}>
                  <div>
                    <span>
                      <b className={"channel-symbol channel-" + i}>
                        {c.name[0]}
                      </b>
                      {c.name}
                    </span>
                    <strong>{c.revenue == null ? (c.apiLoading ? "Загрузка…" : c.apiError ? "Ошибка API" : "Нет данных API") : money(c.revenue)}</strong>
                  </div>
                  <small className="channel-returns">Возвраты: {c.returns == null ? "—" : money(c.returns)}</small>
                  <div className="track">
                    <span
                      style={{
                        width:
                          Math.max(
                            0,
                            Math.min(
                              100,
                              ((Number(c.revenue) || 0) / Math.max(dashboardRevenueTotal, 1)) * 100,
                            ),
                          ) + "%",
                        background: [
                          "#dd604d",
                          "#9b62a9",
                          "#5783cd",
                          "#7aa28e",
                          "#d4a459",
                        ][i % 5],
                      }}
                    />
                  </div>
                </div>
              ))
          ) : (
            <Empty />
          )}
        </div>
      </div>
      <section className="panel dashboard-marketplace-source-panel" aria-label="Сводки маркетплейсов">
        <div className="panel-heading">
          <div><h2>Данные Kaspi и Wildberries</h2><span>Те же итоги и период, что в отдельных страницах маркетплейсов</span></div>
        </div>
        <div className="bottom-grid">
          {dashboardMarketplaceSources.map(({channel, state}) => {
            const data = state.data || {};
            const metrics = channel === "Kaspi" ? [
              ["Выручка API за вычетом возвратов", data.api_revenue == null ? "Нет подтверждённых данных" : money(data.api_revenue)],
              ["Возвраты API", data.api_returns == null ? "—" : money(data.api_returns)],
              ["Продано", data.api_units == null ? "—" : data.api_units + " шт."],
              [Number(data.commission_estimated || 0) > 0 ? "Комиссия (расчётная)" : "Комиссия", money(data.commission)],
              ["Логистика продавца", money(data.logistics)],
              ["Доставка возврата", money(data.return_logistics)],
              ["К получению (расчёт)", data.kaspi_estimated_proceeds == null ? "—" : money(data.kaspi_estimated_proceeds)],
              ["Чистая прибыль", data.net_profit == null ? "—" : money(data.net_profit)],
            ] : [
              ["Оборот продаж WB", data.api_revenue == null ? "Нет данных" : money(data.api_revenue)],
              ["Продано", data.api_units == null ? "—" : data.api_units + " шт."],
              ["К перечислению по финансовому отчёту", Number(data.settlement_rows || 0) > 0 ? money(data.settlement_accrued) : "Нет данных отчёта"],
              ["Комиссия", money(data.commission)],
              ["Логистика продавца", money(data.logistics)],
              ["Реклама", money(data.advertising)],
              ["Чистая прибыль", data.net_profit == null ? "—" : money(data.net_profit)],
            ];
            return <div className="panel" key={channel}>
              <div className="panel-heading"><h3>{channel}</h3><a className="text-button" href={"#" + channel}>Открыть отчёт</a></div>
              {state.loading && !state.data ? <p className="muted">Загружаем данные…</p> :
                state.error ? <p className="error-box" role="alert">Не удалось загрузить сводку: {state.error}</p> :
                <div className="secondary-kpis compact-kpis">{metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>}
            </div>;
          })}
        </div>
      </section>
      <div className="secondary-kpis">
        {[
          ["Продано единиц", r.units, false],
          ["Возвраты", r.returns, true],
          ["Реклама", r.advertising, true],
          ["Расходы", r.expenses, true],
          ["Стоимость склада", r.stock_value, true],
          ["Деньги", r.cash, true],
          ["B2B задолженность", r.b2b_debt, true],
          ["Денежный поток", r.cash_flow, true],
          ["Kaspi API оборот", dashboardKaspiSummary.data?.api_revenue ?? null, true],
           ["WB API оборот", dashboardWbSummary.data?.api_revenue ?? null, true],
          ["Ozon оборот", dash?.selected?.channels?.Ozon || 0, true],
          ["Offline оборот", dash?.selected?.channels?.Offline || 0, true],
          ["B2B оборот", dash?.selected?.channels?.B2B || 0, true],
        ].map(([k, v, m]) => (
          <div key={k}>
            <span>{k}</span>
            <strong>{m ? money(v) : decimal(v)}</strong>
          </div>
        ))}
      </div>
      <div className="bottom-grid profitability-grid">
        <div className="panel">
          <div className="panel-heading"><div><h2>Прибыль по каналам</h2><span>Kaspi · WB · Ozon · Offline · B2B</span></div></div>
          <Table rows={r.channel_summary || []} cols={["channel", "quantity", "revenue", "cogs", "costs", "profit"]} />
        </div>
        <div className="panel">
          <div className="panel-heading"><div><h2>B2B</h2><span>Финансовый учёт без CRM</span></div></div>
          <div className="secondary-kpis compact-kpis">
            <div><span>Оборот</span><strong>{money(r.b2b?.revenue || 0)}</strong></div>
            <div><span>Валовая прибыль</span><strong>{money(r.b2b?.gross_profit)}</strong></div>
            <div><span>Чистая прибыль</span><strong>{money(r.b2b?.net_profit)}</strong></div>
            <div><span>Средний чек</span><strong>{money(r.b2b?.average_check || 0)}</strong></div>
            <div><span>Дебиторка</span><strong>{money(r.b2b?.receivables || 0)}</strong></div>
          </div>
        </div>
      </div>
      <div className="panel category-profit-panel">
        <div className="panel-heading"><div><h2>Прибыль по категориям</h2><span>Contribution profit = после прямых комиссий, логистики и рекламы</span></div></div>
        <Table rows={r.categories || []} cols={["category", "quantity", "revenue", "cogs", "gross_profit", "contribution_profit"]} />
      </div>
      <div className="bottom-grid">
        <div className="panel">
          <div className="panel-heading">
            <div>
              <h2>Товары, которые приносят прибыль</h2>
              <span>По валовой прибыли за период</span>
            </div>
            <button
              className="text-button"
              onClick={() => ctx.navigate("products")}
            >
              Все товары
            </button>
          </div>
          <Table
            rows={[...r.products]
              .sort((a, b) => b.gross_profit - a.gross_profit)
              .slice(0, 5)}
            cols={["name", "quantity", "revenue", "gross_profit"]}
          />
        </div>
        <div className="insight-panel">
          <span className="pill">
            <Sparkles size={14} /> BUSINESS SIGNALS
          </span>
          <h2>
            На что обратить
            <br />
            внимание сегодня
          </h2>
          <div className="insight">
            <span className="insight-num">{r.stock_alerts.length}</span>
            <p>товаров на минимальном остатке</p>
          </div>
          <div className="insight">
            <span className="insight-num">{r.slow_products.length}</span>
            <p>товаров без продаж за период</p>
          </div>
          <button
            onClick={() =>
              ctx.navigate(can(ctx.auth, "ai") ? "assistant" : "alerts")
            }
            className="secondary"
          >
            {can(ctx.auth, "ai") ? "Обсудить с AI" : "Открыть уведомления"}
          </button>
        </div>
      </div>
      {page === "analytics" && (
        <>
          <div className="panel">
            <div className="panel-heading">
              <h2>Медленно продающиеся товары</h2>
            </div>
            <Table rows={r.slow_products} cols={columns.stock} />
          </div>
          <div className="panel">
            <div className="panel-heading">
              <h2>Прибыль по аккаунтам</h2>
              <span>Без нераспределённых общих расходов</span>
            </div>
            <Table
              rows={r.channels.map((c) => ({ ...c, gross_profit: c.profit }))}
              cols={["name", "revenue", "cogs", "gross_profit"]}
            />
          </div>
        </>
      )}
      <p className="method">
        {r.method}. {r.scope_note}.
      </p>
    </>
  );
}
function ReportDetails({ ctx, detail, onClose, activeOnly = false }) {
  const path = "/report/details?start=" + ctx.start + "&end=" + ctx.end + "&metric=" + detail.metric + (ctx.company ? "&company_id=" + ctx.company : "") + (detail.account_id ? "&account_id=" + detail.account_id : "") + (activeOnly ? "&active_only=true" : "");
  const { data, error, loading } = useLoad(path, ctx.refresh);
  return (
    <div className="modal-backdrop report-detail-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section className="modal report-detail-modal" role="dialog" aria-modal="true" aria-label={detail.title}>
        <div className="modal-heading">
          <div><h2>{detail.title}</h2><p>Расшифровка до первичных операций · {ctx.start} — {ctx.end}</p></div>
          <button className="icon-button" onClick={onClose} aria-label="Закрыть"><X size={20}/></button>
        </div>
        {loading ? <Spinner/> : error ? <ErrorBox error={error}/> : <>
          <div className="reconcile-strip">
            <div><span>В отчёте</span><strong>{money(data.expected)}</strong></div>
            <div><span>Расшифровано</span><strong>{money(data.explained)}</strong></div>
            <div className={data.difference === 0 ? "reconcile-ok" : "reconcile-bad"}><span>Расхождение</span><strong>{money(data.difference)}</strong></div>
          </div>
          {data.difference !== 0 && <div className="error-box">Сверка не сошлась. Такой отчёт нельзя считать подтверждённым.</div>}
          <div className="report-detail-table"><Table rows={data.rows} cols={["date","type","reference","description","amount"]} refs={ctx.refs}/></div>
          <p className="panel-note">Источник — проведённые записи ERP. AI в расчёте этой суммы не участвует.</p>
        </>}
      </section>
    </div>
  );
}

function MarketplaceRecordDetails({ ctx, detail, onClose }) {
  const params = new URLSearchParams({channel:detail.channel,metric:detail.metric,start:ctx.start,end:ctx.end});
  if (ctx.company) params.set("company_id", ctx.company);
  if (detail.account_id) params.set("account_id", detail.account_id);
  const {data,error,loading} = useLoad(`/marketplace-record-details?${params}`, ctx.refresh);
  const items = data?.items || [];
  const amount = (item) => item.amount == null ? "Не подтверждено API" : `${Number(item.amount).toLocaleString("ru-RU", {minimumFractionDigits:2,maximumFractionDigits:2})} ${item.currency || ""}`;
  return <div className="modal-backdrop report-detail-backdrop" onMouseDown={(e)=>e.target===e.currentTarget&&onClose()}>
    <section className="modal report-detail-modal marketplace-record-detail" role="dialog" aria-modal="true" aria-label={detail.title}>
      <div className="modal-heading"><div><h2>{detail.title}</h2><p>{detail.channel} · {ctx.start} — {ctx.end}{detail.store ? ` · ${detail.store}` : " · все магазины"}</p></div><button className="icon-button" onClick={onClose} aria-label="Закрыть"><X size={20}/></button></div>
      {loading ? <Spinner/> : error ? <ErrorBox error={error}/> : <>
        {data?.note && <p className="marketplace-record-note">{data.note}</p>}
        {items.length ? <div className="report-detail-table"><table className="data-table"><thead><tr><th>Дата</th><th>Магазин</th><th>Операция</th><th>Заказ / ID</th><th>Товар / SKU</th><th>Кол-во</th><th>Статус</th><th>Сумма источника</th></tr></thead><tbody>{items.map((item)=><tr key={`${item.account_id}:${item.id}`}>
          <td>{item.event_date || "API не передал дату"}</td><td>{item.store}</td><td>{item.operation}</td><td>{item.reference || "—"}</td><td>{item.product_name}{item.sku ? <small className="muted">{item.sku}</small> : null}</td><td>{item.quantity == null ? "—" : `${item.quantity} шт.`}</td><td>{item.status}</td><td>{amount(item)}</td>
        </tr>)}</tbody></table></div> : <Empty text="За выбранный период API-строки не найдены."/>}
        <p className="panel-note">Показаны только поля из сохранённых ответов API. Финансовые расчёты ERP здесь не изменяются.</p>
      </>}
    </section>
  </div>;
}

const ChartIcon = TrendingUp;
function Forecast({ ctx }) {
  const { data, error, loading } = useLoad(
    "/forecast?start=" +
      ctx.start +
      "&end=" +
      ctx.end +
      (ctx.company ? "&company_id=" + ctx.company : ""),
    ctx.refresh,
  );
  return (
    <div className="panel">
      <div className="panel-heading">
        <h2>Прогноз на 30 дней</h2>
        <span className="badge gray">Статистический расчёт</span>
      </div>
      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox error={error} />
      ) : data.status === "insufficient_data" ? (
        <Empty text={data.message} />
      ) : (
        <>
          <div className="secondary-kpis">
            <div>
              <span>Ожидаемая выручка</span>
              <strong>{money(data.revenue)}</strong>
            </div>
            <div>
              <span>Ожидаемая чистая прибыль</span>
              <strong>{money(data.net_profit)}</strong>
            </div>
          </div>
          <p className="panel-note">{data.method}</p>
          <Table
            rows={data.reorder.map((x) => ({
              name: x.name,
              "Дней запаса": x.days_left,
              "Рекомендуемый закуп": x.suggested_quantity,
            }))}
            cols={["name", "Дней запаса", "Рекомендуемый закуп"]}
          />
        </>
      )}
    </div>
  );
}
function Stock({ ctx }) {
  const [batchOffset, setBatchOffset] = useState(0);
  const { data, error, loading } = useLoad(
    "/stock" + (ctx.company ? "?company_id=" + ctx.company : ""),
    ctx.refresh,
  );
  const batchParams = new URLSearchParams({limit:"100", offset:String(batchOffset)});
  if (ctx.company) batchParams.set("company_id", ctx.company);
  const batches = useLoad("/data/batches?" + batchParams.toString(), ctx.refresh);
  const stockById = new Map((data || []).map(row => [row.product_id, row]));
  const displayStock = (ctx.refs.products || []).filter(p => p.active !== false && (p.catalog_kind || "master") === "master").filter(p => {
    if (!ctx.company) return true;
    const ids = (p.company_ids || p.specifications?._qor_company_ids || []).map(Number);
    return ids.includes(Number(ctx.company));
  }).map(p => stockById.get(p.id) || {product_id:p.id, sku:p.sku, name:p.name, quantity:0, sold:0, value:0});
  return (
    <div className="panel">
      <div className="panel-heading">
        <h2>Остатки товаров</h2>
        <div className="stock-actions">
          {can(ctx.auth, "inventory", true) && <button className="primary" onClick={() => ctx.open("adjustments", {kind:"receipt", quantity:1})}><Plus size={16}/>Добавить приход</button>}
          {can(ctx.auth, "sales", true) && <button className="primary" onClick={() => {
            const account = (ctx.refs.accounts || []).find(a => a.channel === "Offline" && (!ctx.company || a.company_id == ctx.company));
            if (!account) {
              ctx.open("accounts", {company_id:ctx.company || ctx.refs.companies?.[0]?.id || "", name:"Офлайн продажи", channel:"Offline"});
              return;
            }
            ctx.open("sales", {account_id:account.id, company_id:ctx.company || account.company_id});
          }}><Plus size={16}/>Записать офлайн-продажу</button>}
          {can(ctx.auth, "inventory", true) && <button className="secondary" onClick={() => ctx.open("adjustments")}><Plus size={16}/>Корректировка</button>}
        </div>
      </div>
      <p className="panel-note">
        Это общий физический остаток компании для всех каналов. При офлайн-продаже внесите товар, количество, цену и дату — проведённая продажа спишет товар со склада и попадёт в канал «Offline». Возврат денег сам по себе склад не пополняет.
        Каждый приход создаёт отдельную партию с датой и количеством. Продажи списываются по FIFO; история партий сохраняется отдельно. Для пересчёта используйте корректировку; списание и брак требуют причины.
      </p>
      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox error={error} />
      ) : (
        <>
          <div className="qor-stock-desktop table-scroll">
            <table className="qor-stock-table">
              <thead><tr><th>Товар / SKU</th><th>Карточки маркетплейсов</th><th>Текущий остаток</th><th>Продано за месяц</th><th>Себестоимость</th><th>Стоимость остатка</th><th>Действия</th></tr></thead>
              <tbody>{displayStock.map((row) => {
                const product = ctx.refs.products?.find((p) => p.id === row.product_id);
                const companyIds = (row.company_ids || product?.company_ids || []).map(Number);
                const productCompany = ctx.company || (companyIds.length === 1 ? companyIds[0] : "");
                const links = (product?.marketplace_links || []).filter(link => link.active && link.mapping_status === "linked");
                const linkLabels = links.map(link => link.channel + " · " + (link.account_name || link.account_id) + (link.external_key ? " · " + link.external_key : ""));
                return <tr key={row.product_id}>
                  <td><div className="qor-stock-product-cell"><ProductImage product={product}/><span><b>{row.name || product?.name || "Товар"}</b><small>Артикул · {product?.article || "—"} · SKU · {row.sku || "—"} · Штрихкод · {product?.barcode || "—"}</small></span></div></td>
                  <td>{linkLabels.length ? linkLabels.map((label,index)=><small className="qor-stock-link" key={row.product_id + "-" + index}>{label}</small>) : <span className="muted">Карточки не связаны</span>}</td>
                  <td><b>{row.quantity ?? 0} шт.</b>{Number(row.min_stock || product?.min_stock || 0)>0 && <small className="qor-table-sub">Минимум · {row.min_stock ?? product?.min_stock} шт.</small>}</td>
                  <td>{row.sold ?? 0} шт.</td>
                  <td>{product?.purchase_cost ? money(product.purchase_cost) : "—"}</td>
                  <td>{row.value == null ? "—" : money(row.value)}</td>
                  <td><div className="qor-stock-row-actions">
                    {productCompany && can(ctx.auth,"inventory",true) && <><button type="button" className="stock-step-button add" aria-label={"Добавить остаток: " + row.name} title="Добавить приход" onClick={()=>ctx.open("adjustments",{company_id:Number(productCompany),product_id:Number(row.product_id),date:today(),quantity:1,unit_cost:product?.purchase_cost || 0,kind:"receipt",reason:"Приход товара"})}>+</button><button type="button" className="stock-step-button" aria-label={"Списать остаток: " + row.name} title="Списание" disabled={Number(row.quantity||0)<=0} onClick={()=>ctx.open("adjustments",{company_id:Number(productCompany),product_id:Number(row.product_id),date:today(),quantity:-1,unit_cost:0,kind:"writeoff",reason:"Списание товара"})}>−</button></>}
                    {can(ctx.auth,"catalog",true) && product && <button type="button" className="secondary" onClick={()=>ctx.open("products",product)}>Изменить товар</button>}
                  </div></td>
                </tr>;
              })}</tbody>
            </table>
          </div>
          <div className="qor-stock-mobile qor-item-grid qor-stock-list">{displayStock.map((row) => {
            const product = ctx.refs.products?.find((p) => p.id === row.product_id);
            const companyIds = (row.company_ids || product?.company_ids || []).map(Number);
            const productCompany = ctx.company || (companyIds.length === 1 ? companyIds[0] : "");
            return <StockItemCard key={row.product_id} row={row} product={product} company={productCompany} ctx={ctx}/>;
          })}</div>
        </>
      )}
      <section className="panel stock-lot-history">
        <div className="section-heading"><div><h3>История приходов по партиям</h3><p className="muted">Каждое поступление хранится отдельной строкой: дата, принято, продано, возвращено и остаток партии.</p></div></div>
        {batches.loading ? <Spinner/> : batches.error ? <ErrorBox error={batches.error}/> : !batches.data?.items?.length && batchOffset === 0 ? <Empty/> : <><div className="table-scroll"><table><thead><tr><th>Дата прихода</th><th>Товар / SKU</th><th>Поступило</th><th>Продано</th><th>Возвращено</th><th>Остаток партии</th></tr></thead><tbody>{(batches.data?.items || []).map(batch=>{const product=ctx.refs.products?.find(p=>p.id===batch.product_id);return <tr key={batch.id}><td>{batch.date}</td><td>{product?.name || "Товар"}<small className="muted"> · {product?.sku || `#${batch.product_id}`}</small></td><td>{batch.quantity} шт.</td><td>{batch.sold_quantity ?? 0} шт.</td><td>{batch.returned_quantity ?? 0} шт.</td><td><b>{batch.remaining} шт.</b></td></tr>})}</tbody></table></div><div className="stock-actions"><button className="secondary" disabled={batchOffset===0} onClick={()=>setBatchOffset(Math.max(0,batchOffset-100))}>Назад</button><span className="muted">Показано {batchOffset+1}–{Math.min(batchOffset+(batches.data?.items?.length || 0), batches.data?.total || 0)} из {batches.data?.total || 0}</span><button className="secondary" disabled={batchOffset+100 >= (batches.data?.total || 0)} onClick={()=>setBatchOffset(batchOffset+100)}>Дальше</button></div></>}
      </section>
    </div>
  );
}
function StockItemCard({row,product,company,ctx}) {
  const [mode,setMode]=useState("");
  const [quantity,setQuantity]=useState("1");
  const [date,setDate]=useState(today());
  const [unitCost,setUnitCost]=useState("");
  const [reason,setReason]=useState("");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const submitLock=useRef(false);
  const current=Number(row.quantity||0);
  const linkedMarketplaceCounts = (product?.marketplace_links || []).reduce((groups, link) => {
    if (!link.active || link.mapping_status !== "linked") return groups;
    const channel = String(link.channel || "").toLocaleLowerCase("ru-RU");
    const key = channel.includes("kaspi") ? "kaspi" : channel.includes("wildberries") || channel === "wb" ? "wildberries" : channel.includes("ozon") ? "ozon" : null;
    if (key) groups[key] = (groups[key] || 0) + 1;
    return groups;
  }, {});
  const marketplaceBadges = [
    ["kaspi", "K", "Kaspi"],
    ["wildberries", "WB", "WB"],
    ["ozon", "O", "Ozon"],
  ].filter(([key]) => linkedMarketplaceCounts[key])
    .map(([key, icon, label]) => ({key, icon, label, stores:linkedMarketplaceCounts[key]}));
  const receipt=mode==="receipt";
  const open=(nextMode)=>{
    setMode(nextMode);
    setQuantity("1");
    setDate(today());
    setUnitCost(product?.purchase_cost>0?String(product.purchase_cost/100):"");
    setReason(nextMode==="receipt"?"Приход товара":"");
    setError("");
  };
  const submit=async e=>{
    e.preventDefault();
    if(submitLock.current||busy)return;
    const amount=Number(quantity);
    const cost=Number(String(unitCost).replace(",","."));
    if(!Number.isInteger(amount)||amount<1){setError("Введите целое количество не меньше 1");return;}
    if(!company){setError("Выберите компанию в верхнем фильтре склада");return;}
    if(!date){setError("Выберите дату движения");return;}
    if(receipt&&(!Number.isFinite(cost)||cost<=0||unitCost==="")){setError("Укажите себестоимость за единицу больше 0 ₸, чтобы партия корректно участвовала в расчёте себестоимости");return;}
    if(!receipt&&amount>current){setError("Нельзя списать больше текущего остатка");return;}
    if(!receipt&&reason.trim().length<5){setError("Укажите причину списания не короче 5 символов");return;}
    submitLock.current=true;setBusy(true);setError("");
    try{
      await api("/post/adjustments",{method:"POST",body:{
        company_id:Number(company),product_id:Number(row.product_id),date,
        quantity:receipt?amount:-amount,unit_cost:receipt?Math.round(cost*100):0,
        kind:receipt?"receipt":"writeoff",reason:reason.trim(),
        reference:"stock-"+(receipt?"receipt":"writeoff")+":"+globalThis.crypto.randomUUID()
      }});
      ctx.notify(receipt?"Приход "+amount+" шт. сохранён":"Списание "+amount+" шт. сохранено");
      setMode("");
    }catch(e){setError(e.message||"Не удалось сохранить складское движение");}
    finally{submitLock.current=false;setBusy(false);}
  };
  return <article className="qor-item-card stock-product-card">
    <ProductImage product={product}/>
    <div className="qor-item-body">
      <span className="marketplace-product-meta">SKU · {row.sku || "—"}</span>
      <h3>{row.name || "Товар без названия"}</h3>
      <div className="stock-marketplace-badges" aria-label="Связанные маркетплейсы">
        {marketplaceBadges.map(({key, icon, label, stores}) => <span key={key} className={`stock-marketplace-badge is-${key}`} aria-label={`${label}, магазинов: ${stores}`}><b aria-hidden="true">{icon}</b>{label}{stores > 1 && <small>×{stores}</small>}</span>)}
        {!marketplaceBadges.length && <span className="stock-marketplace-unlinked">Карточки не связаны</span>}
      </div>
      {!company && <p className="muted">Выберите одну компанию в верхнем фильтре, чтобы менять остаток.</p>}
      <div className="stock-quantity-control" aria-label="Остаток товара">
        <span>Остаток</span>
        <div>
          <button type="button" className="stock-step-button" aria-label={current>0?"Списать товар":"Списание недоступно"} disabled={!company||!can(ctx.auth,"inventory",true)||current<=0||busy} onClick={()=>open("writeoff")}>−</button>
          <strong>{current}<small> шт.</small></strong>
          <button type="button" className="stock-step-button add" aria-label="Добавить приход" disabled={!company||!can(ctx.auth,"inventory",true)||busy} onClick={()=>open("receipt")}>+</button>
        </div>
        <span className="stock-sold-count">Продано · {row.sold ?? 0} шт.</span>
      </div>
      {Number(row.min_stock ?? product?.min_stock ?? 0) > 0 && current <= Number(row.min_stock ?? product?.min_stock ?? 0) && <div className="stock-low-warning" role="status">{current <= 0 ? "Остаток закончился" : "Мало остатка"} · {current} шт. при минимуме {Number(row.min_stock ?? product?.min_stock ?? 0)} шт.</div>}
      {row.value != null && <div className="qor-item-price">Стоимость · {money(row.value)}</div>}
      {mode&&<form className="stock-inline-entry" onSubmit={submit}>
        <div className="stock-inline-heading"><strong>{receipt?"Новый приход":"Списание со склада"}</strong><span>{receipt?"После прихода будет "+(current+Number(quantity||0))+" шт.":"После списания останется "+Math.max(0,current-Number(quantity||0))+" шт."}</span></div>
        <label>Количество, шт.
          <div className="stock-entry-stepper">
            <button type="button" className="secondary" aria-label="Уменьшить количество" disabled={Number(quantity)<=1} onClick={()=>setQuantity(String(Math.max(1,Number(quantity||1)-1)))}>−</button>
            <input type="number" min="1" max={receipt?undefined:current} step="1" value={quantity} onChange={e=>setQuantity(e.target.value)} required/>
            <button type="button" className="secondary" aria-label="Увеличить количество" disabled={!receipt&&Number(quantity)>=current} onClick={()=>setQuantity(String(Number(quantity||0)+1))}>+</button>
          </div>
        </label>
        <label>{receipt?"Дата прихода":"Дата списания"}<input type="date" value={date} onChange={e=>setDate(e.target.value)} required/></label>
        {receipt?<label>Себестоимость за единицу · ₸<input type="number" min="0" step="0.01" value={unitCost} onChange={e=>setUnitCost(e.target.value)} placeholder="Введите себестоимость" required/></label>:<label>Причина списания<textarea rows="2" minLength="5" value={reason} onChange={e=>setReason(e.target.value)} placeholder="Например: передача товара или брак" required/></label>}
        {error&&<p className="stock-entry-error" role="alert">{error}</p>}
        <div className="stock-entry-actions"><button type="button" className="secondary" onClick={()=>setMode("")} disabled={busy}>Отмена</button><button type="submit" className="primary" disabled={busy}>{busy?"Сохраняем…":receipt?"Сохранить приход":"Сохранить списание"}</button></div>
      </form>}
    </div>
  </article>;
}

function MarketplaceProductCard({ p, channel }) {
  const candidates = Array.from(new Set([p.image_url, ...(p.images || [])].filter(Boolean)));
  const [imageIndex, setImageIndex] = useState(0);
  const [imageFailed, setImageFailed] = useState(candidates.length === 0);
  const [expanded, setExpanded] = useState(false);
  const has = (value) => value !== null && value !== undefined;
  const expense = (value) => has(value) ? money(value) : "—";
  const marketplaceLabel = channel === "Wildberries" ? "WB" : channel;
  const onImageError = () => {
    if (imageIndex + 1 < candidates.length) setImageIndex((i) => i + 1);
    else setImageFailed(true);
  };
  return <article className="marketplace-product-card">
    <div className="marketplace-product-image">
      {!imageFailed && candidates[imageIndex] ? <img src={candidates[imageIndex]} alt="" loading="lazy" referrerPolicy="no-referrer" onError={onImageError}/> : <div className="marketplace-product-image-empty"><ImageIcon size={30}/><span>Фото недоступно</span></div>}
      <span className="marketplace-product-source">{marketplaceLabel}</span>
    </div>
    <div className="marketplace-product-body">
      <div className="marketplace-product-title" title={p.name || p.sku}>{p.name || p.sku || "Товар без названия"}</div>
      <div className="marketplace-product-meta">SKU: {p.sku || "—"}{p.brand ? ` · ${p.brand}` : ""}</div>
      <div className="marketplace-product-main"><strong>{has(p.price) ? money(p.price) : "Цена —"}</strong><span>Остаток <b>{has(p.stock_quantity) ? `${p.stock_quantity} шт.` : "—"}</b></span></div>
      <div className="marketplace-product-stats">
        <div><span>За период</span><b>{p.sold_units ?? 0} шт.</b><small>{money(p.revenue || 0)}</small></div>
        <div><span>За всё время</span><b>{p.lifetime_sold_units ?? 0} шт.</b><small>{money(p.lifetime_revenue || 0)}</small></div>
      </div>
      <div className="marketplace-product-costs">
        <div><span>Комиссия</span><b>{expense(p.commission)}</b></div>
        <div><span>Логистика</span><b>{expense(p.logistics)}</b></div>
        <div><span>Реклама</span><b>{expense(p.advertising)}</b></div>
        <div><span>Себестоимость / шт.</span><b>{has(p.unit_cost) ? money(p.unit_cost) : "Не задана"}</b></div>
      </div>
      <button type="button" className="marketplace-product-more" onClick={()=>setExpanded(v=>!v)}>{expanded ? "Скрыть" : "Подробнее"}</button>
      {expanded && <div className="marketplace-product-details">
        <div><span>Категория</span><b>{p.category || "—"}</b></div>
        <div><span>Себестоимость</span><b>{expense(p.cogs)}</b></div>
        <div><span>Прибыль</span><b>{p.profit == null ? "Ожидает себестоимость" : money(p.profit)}</b></div>
        <small className="muted">Себестоимость задаётся в единой карточке товара по SKU. Новое значение действует со следующего дня и не меняет уже проданные товары.</small>
      </div>}
    </div>
  </article>;
}

function ProductImage({ product, label = "Фото не добавлено" }) {
  const images = Array.from(new Set((product?.media || []).filter((x) => typeof x === "string" && /^(https?:\/\/|data:image\/)/i.test(x))));
  const [index, setIndex] = useState(0);
  const [failed, setFailed] = useState(images.length === 0);
  const imageKey = images.join("|");
  useEffect(() => { setIndex(0); setFailed(imageKey.length === 0); }, [imageKey]);
  return <div className="qor-item-image">
    {!failed && images[index] ? <img src={images[index]} alt={product?.name || ""} loading="lazy" referrerPolicy="no-referrer" onError={() => index + 1 < images.length ? setIndex((n) => n + 1) : setFailed(true)}/> : <div className="qor-item-image-empty"><ImageIcon size={30}/><span>{label}</span></div>}
  </div>;
}

function productLinkSummary(product) {
  const links = product.marketplace_links || [];
  const active = links.filter(link => link.active);
  return {
    links,
    linked: active.filter(link => link.mapping_status === "linked").length,
    needsLink: active.filter(link => link.mapping_status === "needs_link").length,
    errors: active.filter(link => link.sync_attention).length,
    complete: active.length > 0 && active.every(link => link.mapping_status === "linked"),
  };
}

function ProductCatalogCard({ product, onEdit, onDelete, onPrice, selected, onSelect, accounts = [], onSync }) {
  const links = productLinkSummary(product);
  return <article className="qor-item-card">
    <ProductImage product={product}/>
    <div className="qor-item-body">
      <div className="catalog-product-heading">
        <label className="catalog-select"><input type="checkbox" checked={selected} onChange={onSelect}/> Выбрать</label>
        <span className="catalog-product-sku">SKU · {product.sku || "—"}</span>
      </div>
      <h3 className="catalog-product-title">{product.name || "Товар без названия"}</h3>
      <div className="catalog-product-price-row"><strong>{Number(product.price || 0) > 0 ? money(product.price) : "Цена не указана"}</strong><span>Себестоимость<br/><b>{Number(product.purchase_cost || 0) > 0 ? money(product.purchase_cost) : "Не задана"}</b></span></div>
      <div className="catalog-primary-facts"><div><span>Связано магазинов</span><strong>{links.linked}/{links.links.filter(link=>link.active).length}</strong></div><div><span>Карточек / ID</span><strong>{links.links.reduce((n,link)=>n+Number(link.mapping_count||0),0)}</strong></div></div>
      <details className="catalog-link-details">
        <summary><b>Карточки маркетплейсов</b><span>{links.linked} связано · {links.needsLink} требуют связи{links.errors ? ` · ${links.errors} с ошибкой` : ""}</span></summary>
        {links.links.length ? <div className="catalog-link-list">{links.links.map(link=><div className="catalog-link-row" key={link.account_id}>
          <div><strong>{link.channel} · {link.account_name}</strong><small>{link.mapping_status === "linked" ? `ID: ${link.external_keys.join(", ")}` : link.mapping_status === "inactive" ? "Связь сохранена, магазин отключён" : "Карточки ещё не связаны с этим SKU"}</small></div>
          <span className={`catalog-link-badge ${link.mapping_status === "linked" ? "is-linked" : link.mapping_status === "inactive" ? "is-inactive" : "is-unlinked"}`}>{link.mapping_status === "linked" ? `Связано · ${link.mapping_count} ID` : link.mapping_status === "inactive" ? "Отключён" : "Требует связи"}</span>
          {link.sync_attention && <small className="catalog-link-error">{link.sync_status_label}. {link.sync_attention_message}</small>}
          {link.mapping_status === "needs_link" && <button type="button" className="secondary" onClick={()=>onEdit(link.account_id)}>Связать магазин</button>}
        </div>)}</div> : <p className="catalog-empty-sales">Добавьте одну или несколько карточек Kaspi/Wildberries в карточке SKU.</p>}
        <small className="catalog-mapping-note">Для одного товара можно указать несколько аккаунтов и несколько ID карточек в каждом магазине.</small>
      </details>
      <div className="row-actions catalog-product-actions"><button className="secondary" onClick={onEdit}>Изменить / ID</button><button className="secondary" onClick={onPrice}>Цена</button>{[...new Set((product.marketplace_mappings || []).filter(m=>m.channel === "Wildberries").map(m=>m.account_id))].map(id=><button className="secondary" key={id} onClick={()=>onSync?.(id)} title="Синхронизировать связанные карточки WB">Синхр. WB · {accounts.find(a=>a.id === id)?.name || id}</button>)}<button className="icon-button danger" title="Архивировать товар" onClick={onDelete}><Trash2 size={16}/></button></div>
    </div>
  </article>;
}

function ProductCatalogTable({rows,selected,onSelect,onEdit,onPrice,onDelete,accounts}) {
  return <div className="table-scroll"><table className="qor-master-table"><thead><tr><th></th><th>Товар / SKU</th><th>Категория</th><th>Цена</th><th>Себестоимость</th><th>Остаток</th><th>Связанные площадки</th><th>Статус</th><th>Действия</th></tr></thead><tbody>
    {rows.map(product=>{const links=productLinkSummary(product);const inventory=product.inventory?.physical ?? product.quantity ?? product.stock ?? null;return <tr key={product.id}>
      <td><input aria-label={`Выбрать ${product.name || product.sku}`} type="checkbox" checked={selected.includes(product.id)} onChange={()=>onSelect(product.id)}/></td>
      <td><div className="qor-master-product"><ProductImage product={product}/><span><b>{product.name || "Товар без названия"}</b><small>SKU · {product.sku || "—"}{product.article ? ` · Артикул ${product.article}` : ""}</small></span></div></td>
      <td>{product.category || "—"}</td><td>{Number(product.price||0)>0?money(product.price):"—"}</td><td>{Number(product.purchase_cost||0)>0?money(product.purchase_cost):"—"}</td>
      <td><b>{inventory == null ? "—" : `${inventory} шт.`}</b>{product.min_stock != null && <small className="qor-table-sub">Мин. {product.min_stock}</small>}</td>
      <td><div className="qor-marketplace-badges">{links.links.filter(link=>link.mapping_count>0).map(link=><span key={link.account_id} title={link.account_name} className={`qor-marketplace-badge qor-marketplace-badge--${String(link.channel).toLowerCase()}`}>{link.channel === "Wildberries" ? "WB" : link.channel}</span>)}{!links.linked&&<span className="qor-unlinked-badge">Не связано</span>}</div></td>
      <td><span className={`badge ${product.active===false?"gray":"green"}`}>{product.active===false?"Архив":"Активен"}</span></td>
      <td><div className="qor-table-actions"><button className="icon-button" title="Редактировать товар" onClick={()=>onEdit(product)}><Pencil size={15}/></button><button className="icon-button" title="Изменить цену" onClick={()=>onPrice(product)}><Wallet size={15}/></button><button className="icon-button danger" title="Архивировать товар" onClick={()=>onDelete(product)}><Trash2 size={15}/></button></div></td>
    </tr>})}
    {!rows.length&&<tr><td colSpan="9"><Empty text="Товары не найдены"/></td></tr>}
  </tbody></table><small className="qor-catalog-store-count">Магазинов в рабочем пространстве: {accounts.length}</small></div>;
}

function SaleProductCard({ sale, product, account, onReturn }) {
  return <article className="qor-sale-card">
    <ProductImage product={product}/>
    <div className="qor-item-body">
      <div className="qor-sale-heading"><div><span className="marketplace-product-meta">{sale.date || "Дата не указана"} · {account?.name || account?.channel || "Продажа"}</span><h3>{product?.name || "Товар без фото в каталоге"}</h3></div><strong>{money(sale.revenue || 0)}</strong></div>
      <div className="qor-item-facts"><span>SKU · {product?.sku || "—"}</span><b>{sale.quantity ?? 0} шт.</b><span>Заказ · {sale.reference || "—"}</span></div>
      <div className="row-actions"><a className="secondary" href={`/api/sales/${sale.id}/invoice`}><FileText size={15}/> Счёт</a><button className="secondary" onClick={onReturn}><RotateCcw size={15}/> Возврат</button></div>
    </div>
  </article>;
}

function MarketplaceIntegrationCard({row,busy,onConfigure,onSync,onEdit,onDelete}) {
  const channel=String(row.channel||"");
  const state=String(row.sync_status||"never").toLowerCase();
  const disconnected=row.active===false;
  const status=disconnected?"Отключён":state==="running"?"Синхронизация":state==="failed"?"Требует внимания":state==="done"?"Подключён":"Подключён · ещё не синхронизирован";
  const marketplaceClass=channel.toLowerCase()==="wildberries"?"wildberries":channel.toLowerCase();
  return <article className={`qor-integration-card ${disconnected?"is-disconnected":""} ${state==="failed"?"has-error":""}`}>
    <header><span className={`qor-marketplace-mark qor-marketplace-mark--${marketplaceClass}`}>{channel==="Wildberries"?"WB":channel==="Kaspi"?"K":channel.slice(0,2).toUpperCase()}</span><div><b>{channel}</b><small>{row.name || "Магазин"} · {row.company_name || "Компания"}</small></div><span className={`qor-integration-status status-${disconnected?"off":state==="failed"?"error":state==="running"?"running":"ready"}`}><i/>{status}</span></header>
    <div className="qor-integration-facts"><div><span>Последняя синхронизация</span><b>{row.last_sync?new Date(row.last_sync).toLocaleString("ru-RU"):"—"}</b></div><div><span>Статус процесса</span><b>{state==="never"?"Нет запусков":state==="done"?"Завершено":state==="running"?"Выполняется":state==="failed"?"Ошибка":state}</b></div></div>
    {row.sync_error&&<p className="qor-integration-error">{row.sync_error}</p>}
    <footer><button type="button" className="secondary" onClick={()=>onConfigure(row)}>{disconnected?"Подключить магазин":"Настроить"}</button><button type="button" className="primary" disabled={busy||disconnected} onClick={()=>onSync(row)}><RefreshCw size={14}/>{busy&&state==="running"?"Синхронизация…":"Синхронизировать"}</button><button type="button" className="icon-button" title="Изменить магазин" onClick={()=>onEdit(row)}><Pencil size={15}/></button><button type="button" className="icon-button danger" title="Удалить магазин" onClick={()=>onDelete(row)}><Trash2 size={15}/></button></footer>
  </article>;
}

function ProductOperationModal({ operation, company, onClose, onSaved }) {
  const product = operation.product;
  const [value, setValue] = useState(operation.kind === "price" ? String((product.price || 0) / 100) : String(product.inventory?.physical ?? 0));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submitLock = useRef(false);
  const submit = async e => {
    e.preventDefault();
    if (submitLock.current) return;
    submitLock.current = true;
    setBusy(true); setError("");
    try {
      if (operation.kind === "count") {
        const counted = Number(value);
        if (!Number.isInteger(counted) || counted < 0) throw new Error("Введите целое количество от нуля");
        if (reason.trim().length < 5) throw new Error("Укажите причину не короче 5 символов");
        const skuCost = Number(product.purchase_cost || 0);
        if (counted > Number(product.inventory?.physical ?? 0) && skuCost <= 0) throw new Error("Сначала задайте себестоимость в карточке товара по SKU");
        await api("/inventory/count", {method:"POST", body:{company_id:Number(company), product_id:product.id, counted_quantity:counted, unit_cost:skuCost || undefined, reason:reason.trim(), idempotency_key:globalThis.crypto.randomUUID()}});
        onSaved("Остаток пересчитан. Движение записано в историю.");
      } else {
        const price = Math.round(Number(String(value).replace(",", ".")) * 100);
        if (!Number.isFinite(price) || price < 0) throw new Error("Введите корректную цену");
        const body = {version:product.version, description:product.description || "", barcode:product.barcode || "", purchase_cost:product.purchase_cost || 0, custom_fields:product.custom_fields || {}, marketplace_stock_allocations:product.marketplace_stock_allocations || {}, sku:product.sku, name:product.name, category:product.category || "", article:product.article || "", brand:product.brand || "", supplier:product.supplier || "", country:product.country || "", media:product.media || [], currency:product.currency || "KZT", fx_rate:product.fx_rate || 10000, weight_g:product.weight_g || 0, volume_cm3:product.volume_cm3 || 0, min_price:product.min_price || 0, recommended_price:product.recommended_price || 0, price, min_stock:product.min_stock || 0, active:product.active !== false, specifications:product.specifications || {}};
        await api(`/data/products/${product.id}`, {method:"PUT", body});
        onSaved("Цена сохранена");
      }
    } catch(e) { setError(e.message); }
    finally { submitLock.current = false; setBusy(false); }
  };
  const close = () => { if (!busy) onClose(); };
  return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)close()}}><form className="modal product-operation-modal" role="dialog" aria-modal="true" onSubmit={submit}>
    <div className="modal-heading"><div><span className="eyebrow">{operation.kind === "count" ? "СКЛАДСКОЙ ПЕРЕСЧЁТ" : "БЫСТРОЕ ИЗМЕНЕНИЕ ЦЕНЫ"}</span><h2>{product.name}</h2><p className="muted">SKU · {product.sku}</p></div><button type="button" className="icon-button" onClick={close} aria-label="Закрыть"><X/></button></div>
    {operation.kind === "count" ? <>
      <label>Фактическое физическое количество<input autoFocus type="number" min="0" step="1" value={value} onChange={e=>setValue(e.target.value)} required/></label>
      {Number(value) > Number(product.inventory?.physical ?? 0) && <small>Для добавляемого остатка будет использована себестоимость карточки SKU: {product.purchase_cost ? money(product.purchase_cost) : "не задана"}.</small>}
      <label>Причина пересчёта<textarea rows={3} minLength={5} value={reason} onChange={e=>setReason(e.target.value)} required placeholder="Например: инвентаризация склада"/></label>
      <small>ERP создаст отдельное складское движение. Количество не перезаписывается напрямую.</small>
    </> : <label>Новая цена, ₸<input autoFocus type="number" min="0" step="0.01" value={value} onChange={e=>setValue(e.target.value)} required/></label>}
    <ErrorBox error={error}/><div className="modal-actions"><button className="secondary" type="button" onClick={close} disabled={busy}>Отмена</button><button className="primary" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить"}</button></div>
  </form></div>;
}

function WBFinanceReport({ accounts, company, period, start, end }) {
  const range = {start, end};
  const [accountId, setAccountId] = useState("");
  const activeAccountId = accounts.length === 1 ? String(accounts[0].id) : accountId;
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  const [detailFocus, setDetailFocus] = useState("");
  const [opPage, setOpPage] = useState(0);
  const [reportRefresh, setReportRefresh] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [syncStartedAt, setSyncStartedAt] = useState(0);
  const [syncError, setSyncError] = useState("");
  const autoSyncRef = useRef(new Map());
  const [downloadingExcel, setDownloadingExcel] = useState(false);
  const [excelError, setExcelError] = useState("");
  useEffect(() => {
    if (accounts.length && !accounts.some(a=>String(a.id)===String(accountId))) setAccountId(String(accounts[0].id));
    else if (!accounts.length && accountId) setAccountId("");
  }, [accounts, accountId]);
  useEffect(() => setOpPage(0), [start, end, activeAccountId, period]);
  useEffect(() => { setSyncing(false); setSyncStartedAt(0); }, [start, end, activeAccountId, period]);
  const params = new URLSearchParams({ period, start:range.start, end:range.end });
  if (activeAccountId) params.set("account_id", activeAccountId);
  if (company) params.set("company_id", company);
  const report = useLoad(`/wildberries/finance?${params}`, reportRefresh);
  const data = report.data || {};
  useEffect(() => {
    if (!syncing || !syncStartedAt) return;
    const updatedAt = Date.parse(data.updated_at || "");
    const attemptAt = Date.parse(data.attempt_at || "");
    const completed = ["готов", "ожидается", "частично"].includes(data.status) && updatedAt >= syncStartedAt - 1000;
    const failed = data.status === "ошибка" && attemptAt >= syncStartedAt - 1000;
    if (completed || failed) {
      setSyncing(false);
      setSyncStartedAt(0);
    }
  }, [syncing, syncStartedAt, data.status, data.updated_at, data.attempt_at]);
  useEffect(() => {
    if (!syncing && data.status !== "загружается") return undefined;
    const timer = window.setInterval(() => setReportRefresh((v) => v + 1), 20000);
    return () => window.clearInterval(timer);
  }, [syncing, data.status]);
  useEffect(() => {
    if (data.status !== "ожидается") return undefined;
    const updatedAt = Date.parse(data.updated_at || "");
    const retryAfter = 15 * 60 * 1000;
    const delay = Number.isFinite(updatedAt) ? Math.max(1000, retryAfter - (Date.now() - updatedAt)) : 1000;
    const timer = window.setTimeout(() => setReportRefresh((v) => v + 1), delay);
    return () => window.clearTimeout(timer);
  }, [data.status, data.updated_at]);
  const startReportSync = useCallback(async () => {
    if (!activeAccountId) return;
    setSyncError("");
    setSyncing(true);
    setSyncStartedAt(Date.now());
    try {
      const query = new URLSearchParams({ period, start:range.start, end:range.end, account_id: activeAccountId });
      await api(`/wildberries/finance/sync?${query}`, { method: "POST" });
      setReportRefresh((v) => v + 1);
    } catch (error) {
      setSyncing(false);
      setSyncStartedAt(0);
      setSyncError(error.message);
    }
  }, [activeAccountId, period, range.start, range.end]);
  useEffect(() => {
    if (!activeAccountId || report.loading || report.error) return;
    const key = `${activeAccountId}:${period}:${range.start}:${range.end}:${company || ""}`;
    const lastAttempt = autoSyncRef.current.get(key) || 0;
    const matchesRange = data.start === range.start && data.end === range.end && data.period === period;
    const updatedAt = Date.parse(data.updated_at || "");
    const refreshAfterMs = data.status === "ожидается" ? 15 * 60 * 1000 : period === "daily" ? 5 * 60 * 1000 : 60 * 60 * 1000;
    const fresh = matchesRange && ["готов", "ожидается", "частично"].includes(data.status) &&
      Number.isFinite(updatedAt) && Date.now() - updatedAt < refreshAfterMs;
    if (fresh || matchesRange && data.status === "загружается" || Date.now() - lastAttempt < refreshAfterMs) return;
    autoSyncRef.current.set(key, Date.now());
    startReportSync();
  }, [activeAccountId, period, range.start, range.end, company, data.start, data.end, data.period, data.status, data.updated_at, report.loading, report.error, startReportSync]);
  const downloadExcel = async () => {
    setExcelError("");
    setDownloadingExcel(true);
    try {
      const exportParams = new URLSearchParams(params);
      exportParams.set("template", "client");
      await downloadApiFile(`/wildberries/finance.xlsx?${exportParams.toString()}`, `WB-${period}-${range.start}-${range.end}.xlsx`);
    } catch (error) {
      setExcelError(error.message || "Не удалось скачать Excel");
    } finally {
      setDownloadingExcel(false);
    }
  };
  const statusText = data.status === "готов" ? "Готов" : data.status === "загружается" ? "Загружается" : data.status === "частично" ? "Частично" : data.status === "ошибка" ? "Ошибка" : "Ожидается публикация WB";
  const currency = data.currency || "RUB";
  const amount = (v, cur = currency) => v == null ? "Не рассчитана" : `${Number(v).toLocaleString("ru-RU", {minimumFractionDigits:2, maximumFractionDigits:2})} ${cur}`;
  const products = (data.products || []).filter((p) => {
    const term = search.trim().toLowerCase();
    const matches = !term || `${p.article} ${p.name} ${p.sku} ${p.nm_id}`.toLowerCase().includes(term);
    const returns = Number(p.returns_qty || 0) > 0;
    return matches && (kind === "all" || (kind === "returns" ? returns : Number(p.sales_qty || 0) > 0));
  });
  const operations = data.operations || [];
  const focusedOperations = operations.filter((o) => {
    const key = detailFocus.toLowerCase();
    if (key.includes("возврат")) return Boolean(o.is_return);
    if (key.includes("логистик")) return Number(o.direct_logistics || 0) !== 0 || Number(o.reverse_logistics || 0) !== 0 || /логист/i.test(o.operation || "");
    if (key.includes("вознаграждение") || key.includes("ндс") || key.includes("эквайринг")) return Number(o.commission || 0) !== 0 || Number(o.commission_vat || 0) !== 0 || Number(o.acquiring || 0) !== 0;
    if (key.includes("штраф")) return Number(o.penalty || 0) !== 0;
    if (key.includes("хранение")) return Number(o.storage || 0) !== 0;
    if (key.includes("перечислению") || key.includes("выплат")) return true;
    return !o.is_return;
  });
  const pageCount = Math.ceil(operations.length / 200);
  const fields = [["retail","Розничная цена со скидкой"],["realization","WB реализовал товар"],["payout","К перечислению"],["commission","Вознаграждение с продаж"],["wb_reward","Вознаграждение WB без НДС (справочно)"],["commission_vat","НДС с вознаграждения WB"],["acquiring","Эквайринг"],["direct_logistics","Прямая логистика"],["reverse_logistics","Доп. логистика (входит в общую)"],["penalty","Штрафы"],["storage","Хранение"],["other","Прочие"]];
  const totals = data.totals || {};
  // Клиентская сверка: начисление минус прямая логистика, штрафы и хранение.
  // Rebill уже включён в общий логистический конверт и не вычитается второй раз.
  const payoutReady = Number(data.row_count || 0) > 0 && ["payout", "logistics_total", "penalty", "storage"].every((key) => totals[key] != null && Number.isFinite(Number(totals[key])));
  const estimatedClientPayout = payoutReady
    ? (Math.round(Number(totals.payout) * 100) - Math.round(Number(totals.logistics_total) * 100) - Math.round(Number(totals.penalty) * 100) - Math.round(Number(totals.storage) * 100)) / 100
    : null;
  const cogsComplete = data.cogs_complete === true;
  const periodLabel = period === "weekly" ? "Недельный" : period === "monthly" ? "Месячный" : period === "custom" ? "Отчёт за выбранный период" : "Дневной";
  const wbReportMetrics = [
    ["WB реализовал товар",totals.realization],
    ["Возвраты WB (уменьшение начисления)",data.row_count ? -Number(data.returns_amount || 0) : null],
    ["Розничная цена со скидкой",totals.retail],
    ["К перечислению",totals.payout],
    ["ИТОГО к выплате (расчёт по схеме клиента)",estimatedClientPayout],
    ["Вознаграждение с продаж",totals.commission],
    ["НДС с вознаграждения",totals.commission_vat],
    ["Эквайринг",totals.acquiring],
    ["Прямая логистика WB (расчётная)",totals.direct_logistics],
    ["Дополнительная логистика WB (входит в общую)",totals.reverse_logistics],
    ["Логистика всего",data.row_count ? totals.logistics_total : null],
    ["Штрафы",totals.penalty],
    ["Хранение",totals.storage],
    ["Себестоимость",cogsComplete?totals.cogs:null],
    ["Чистая прибыль (после логистики и расходов)",cogsComplete?totals.profit:null],
    ["Маржа, %",cogsComplete?totals.margin_pct:null]
  ];
  const wbMetricButton = ([label,value]) => <button type="button" className="marketplace-report-metric marketplace-kpi-button wb-report-kpi-button" key={label} aria-pressed={detailFocus===label} onClick={()=>{setDetailFocus(detailFocus===label?"":label);setOpPage(0);}}>
    <span>{label}</span><strong>{label==="Маржа, %"? (value==null?"Не рассчитана":`${Number(value).toLocaleString("ru-RU",{minimumFractionDigits:2,maximumFractionDigits:2})}%`) : amount(value)}</strong><small>Открыть расшифровку</small>
  </button>;
  const wbReportGroups = [
    {title:"Продажи и начисления", metrics:[wbReportMetrics[2],wbReportMetrics[0],wbReportMetrics[1],wbReportMetrics[3]]},
    {title:"Удержания и расходы", metrics:wbReportMetrics.slice(5,13)},
    {title:"Себестоимость и прибыль", metrics:wbReportMetrics.slice(13)}
  ];

  return <section className="panel wb-weekly-report" aria-label={`${periodLabel} финансовый отчёт Wildberries`}>
    <div className="section-heading"><div><h3>{periodLabel} финансовый отчёт</h3><p className="muted">Источник — Finance API WB. Основа расчёта — сумма к перечислению; месячный итог агрегируется из дневных строк WB. Это начисление WB, не подтверждение банковского зачисления.</p></div><span className={`pill wb-weekly-status ${data.status === "готов" ? "ready" : ""}`}>{statusText}</span></div>
    <div className="row-actions wb-weekly-controls">
      {accounts.length > 1 && <label>Аккаунт WB<select value={accountId} onChange={(e)=>setAccountId(e.target.value)}>{accounts.map((a)=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}
      <label>Поиск товара<input type="search" value={search} onChange={(e)=>setSearch(e.target.value)} placeholder="Артикул или название"/></label>
      <label>Операции<select value={kind} onChange={(e)=>setKind(e.target.value)}><option value="all">Все</option><option value="sales">Продажи</option><option value="returns">Есть возвраты</option></select></label>
      <button type="button" disabled={!activeAccountId || syncing} onClick={startReportSync}>{syncing ? "Проверяем WB…" : "Проверить WB сейчас"}</button>
      <button type="button" className="button primary" disabled={downloadingExcel || !activeAccountId} onClick={downloadExcel}>{downloadingExcel ? "Скачиваем Excel…" : "Excel как у клиента"}</button>
    </div>
    {syncError && syncError !== report.error && <ErrorBox error={syncError}/>}
    {excelError && <ErrorBox error={excelError}/>}
    {report.loading ? <Spinner/> : report.error ? <ErrorBox error={report.error}/> : <>
      <p className="muted" role="status">Аккаунт WB #{data.account_id ?? activeAccountId} · Период {data.start || data.week_start} — {data.end || data.week_end}. Проверено: {data.updated_at ? new Date(data.updated_at).toLocaleString("ru-RU") : "—"}. {data.status === "ожидается" ? "WB пока не опубликовал финансовые строки. QOR проверит отчёт автоматически через 15 минут; отсутствие строк не считается нулём продаж." : `Строк отчёта: ${data.row_count || 0}.`}</p>
      {data.status === "ошибка" && data.error && <ErrorBox error={data.error}/>}
      <div className="wb-report-overview">
        <article className="wb-report-total">
          <span>Расчёт по схеме клиента</span>
          <strong>{amount(estimatedClientPayout)}</strong>
          <small>Ориентир после логистики, штрафов и хранения · не банковское зачисление</small>
        </article>
        <div className="wb-report-summary">
          {wbMetricButton(wbReportMetrics[0])}
          {wbMetricButton(wbReportMetrics[1])}
          {wbMetricButton(wbReportMetrics[3])}
        </div>
      </div>
      <div className="wb-report-breakdown">{wbReportGroups.map(group=><details className="marketplace-report-details" key={group.title}>
        <summary><span>{group.title}</span><small>{group.metrics.length} показателей</small></summary>
        <div className="marketplace-report-metrics">{group.metrics.map(wbMetricButton)}</div>
      </details>)}</div>
            {detailFocus && <div className="panel wb-report-detail"><div className="section-heading"><div><h4>{detailFocus} · {data.start} — {data.end}</h4><p className="muted">Магазин: {accounts.find(a=>String(a.id)===String(activeAccountId))?.name || `#${activeAccountId}`}. Строки из сохранённого финансового отчёта WB.</p></div><button type="button" onClick={()=>setDetailFocus("")}>Закрыть</button></div>{/себестоимость|прибыл|маржа/i.test(detailFocus) ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Артикул</th><th>Товар</th><th>Продажи</th><th>Возвраты</th><th>Себестоимость</th><th>Прибыль</th></tr></thead><tbody>{products.map(p=><tr key={`focus-${p.article}-${p.sku}`}><td>{p.article}</td><td>{p.name||"—"}</td><td>{p.sales_qty}</td><td>{p.returns_qty}</td><td>{amount(p.cogs,p.currency)}</td><td>{amount(p.profit,p.currency)}</td></tr>)}</tbody></table></div> : <div className="table-wrap"><table className="data-table"><thead><tr><th>Дата</th><th>Операция</th><th>Артикул</th><th>Сумма операции</th><th>Логистика</th><th>Комиссия / НДС</th><th>Эквайринг</th><th>Начисление к перечислению</th><th>ID источника</th></tr></thead><tbody>{focusedOperations.slice(0,500).map(o=><tr key={`focus-${o.external_id}`}><td>{o.date}</td><td>{o.is_return?"Возврат":o.operation||"—"}</td><td>{o.article||"—"}</td><td>{amount(o.raw_amount,o.currency)}</td><td>{amount(o.direct_logistics,o.currency)} / {amount(o.reverse_logistics,o.currency)}</td><td>{amount(o.commission,o.currency)} / {amount(o.commission_vat,o.currency)}</td><td>{amount(o.acquiring,o.currency)}</td><td>{amount(o.amount,o.currency)}</td><td>{o.external_id}</td></tr>)}{!focusedOperations.length&&<tr><td colSpan="8" className="muted">Нет строк операций этого типа за выбранный период.</td></tr>}</tbody></table></div>}</div>}
      {estimatedClientPayout != null && <p className="muted">Итого к выплате — расчётный показатель: к перечислению WB − прямая логистика − штрафы − хранение. Дополнительная логистика (rebill) показывается отдельно. Это не подтверждение банковской выплаты.</p>}
      {!cogsComplete && <p className="muted">Себестоимость заполнена/подтверждена для {data.cogs_costed_products || 0} из {data.cogs_products_total || 0} товаров. Расчёт прибыли неполный: возвраты без подтверждённой FIFO-связи требуют проверки.</p>}
      {data.unallocated_operations > 0 && <p className="muted">{data.unallocated_operations} операций WB без артикула сохранены отдельно. Их расходы входят в общий отчёт, но не распределяются между товарами.</p>}
      <div className="table-wrap"><table className="data-table"><thead><tr><th>Артикул WB / SKU</th><th>Наименование</th><th>Валюта</th><th>Продажи</th><th>Возвраты</th>{fields.map(([,label])=><th key={label}>{label}</th>)}<th>Себестоимость</th><th>Прибыль</th></tr></thead><tbody>
        {products.map((p)=><tr key={`${p.article}-${p.sku}-${p.currency}`}><td>{p.article}{p.sku ? <small className="muted">{p.sku}</small> : null}</td><td>{p.name || "—"}</td><td>{p.currency}</td><td>{p.sales_qty}</td><td>{p.returns_qty}</td>{fields.map(([key])=><td key={key}>{amount(p[key],p.currency)}</td>)}<td>{amount(p.cogs,p.currency)}</td><td>{amount(p.profit,p.currency)}</td></tr>)}
        {products.length === 0 && <tr><td colSpan={7+fields.length} className="muted">{data.status === "готов" ? "За выбранный период нет строк товара; проверьте итоги и финансовые операции ниже." : data.status === "ожидается" ? "Отчёт за этот период пока не опубликован Wildberries. Данные не подменяются нулём." : "Ожидается публикация финансового отчёта WB."}</td></tr>}
        {data.row_count > 0 && <tr className="total-row"><th colSpan={3}>ИТОГО по всем строкам WB</th><th>{data.sales_qty ?? products.reduce((n,p)=>n+Number(p.sales_qty||0),0)}</th><th>{data.returns_qty ?? products.reduce((n,p)=>n+Number(p.returns_qty||0),0)}</th>{fields.map(([key])=><th key={key}>{amount(totals[key])}</th>)}<th>{amount(cogsComplete?totals.cogs:null)}</th><th>{amount(cogsComplete?totals.profit:null)}</th></tr>}
      </tbody></table></div>
      <h4>Финансовые операции WB</h4>
      <div className="table-wrap"><table className="data-table"><thead><tr><th>Дата</th><th>Тип операции</th><th>Артикул</th><th>Сумма WB (исходная)</th><th>Влияние на начисление</th><th>ID источника</th></tr></thead><tbody>{operations.slice(opPage*200,(opPage+1)*200).map((o)=><tr key={o.external_id}><td>{o.date}</td><td>{o.is_return ? "Возврат" : o.operation||"—"}</td><td>{o.article}</td><td>{amount(o.raw_amount,o.currency)}</td><td>{amount(o.amount,o.currency)}</td><td>{o.external_id}</td></tr>)}</tbody></table></div>
      {pageCount>1 && <div className="row-actions"><button type="button" disabled={opPage===0} onClick={()=>setOpPage((v)=>v-1)}>Назад</button><span className="muted">Страница {opPage+1} из {pageCount} · всего операций: {operations.length}</span><button type="button" disabled={opPage+1>=pageCount} onClick={()=>setOpPage((v)=>v+1)}>Далее</button></div>}
    </>}
  </section>;
}

function MarketplaceOrdersReport({channel,ctx,accounts,selectedAccount,canRefresh}) {
  const [filter,setFilter]=useState("all"),[reload,setReload]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const params=new URLSearchParams({channel,status_filter:filter,limit:"200"});
  if(ctx.company) params.set("company_id",ctx.company);
  if(selectedAccount) params.set("account_id",String(selectedAccount.id));
  const data=useLoad("/marketplace-orders?"+params,`${ctx.refresh}:${reload}`);
  const refresh=async()=>{
    setBusy(true);setError("");
    try {
      await Promise.all(accounts.map(a=>api(channel==="Wildberries"?`/accounts/${a.id}/sync-now?background=true&sections=order_statuses`:`/accounts/${a.id}/sync-kaspi-period?start=${encodeURIComponent(ctx.start)}&end=${encodeURIComponent(ctx.end)}&report_mode=created&force=true`,{method:"POST",timeoutMs:15000})));
      setReload(v=>v+1);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  };
  const summary=data.data?.summary||{};
  return <section className="panel marketplace-orders-report"><div className="section-heading"><div><h3>Заказы и товары в пути</h3><p className="muted">Статус берётся из API выбранных магазинов. Сумма заказа не считается выплатой; финансовые расчёты продаж остаются отдельными.</p></div>{canRefresh&&<button type="button" disabled={busy||!accounts.length} onClick={refresh}>{busy?"Обновляем…":"Обновить статусы API"}</button>}</div>
    <div className="row-actions" role="group" aria-label="Фильтр статуса заказа">{[["all","Все"],["in_delivery","В доставке"],["delivered","Доставлены"],["waiting","Ожидают"],["canceled","Отменены"],["returns","Возвраты / брак"]].map(([id,label])=><button key={id} type="button" aria-pressed={filter===id} className={filter===id?"primary":""} onClick={()=>setFilter(id)}>{label}{id==="all"?` · ${data.data?.total||0}`:` · ${summary[id]||0}`}</button>)}</div>
    {error&&<ErrorBox error={error}/ >}{data.loading?<Spinner/>:data.error?<ErrorBox error={data.error}/>:!data.data?.items?.length?<Empty text="Заказы для этого фильтра не найдены."/>:<div className="table-scroll"><table><thead><tr><th>Магазин</th><th>Дата</th><th>Заказ</th><th>Товар / SKU</th><th>Кол-во</th><th>Сумма заказа</th><th>Статус API</th><th>Учёт / деньги</th></tr></thead><tbody>{data.data.items.map((x,i)=><tr key={`${x.account_id}:${x.order_id}:${i}`}><td>{x.store}</td><td>{x.date?new Date(x.date).toLocaleString("ru-RU"):"—"}</td><td>{x.order_id}</td><td>{x.product}{x.sku&&<small className="muted"> · {x.sku}</small>}</td><td>{x.quantity??"—"}</td><td>{x.amount==null?"—":money(Math.round(Number(x.amount)*100))}</td><td><span className={`pill marketplace-order-status marketplace-order-status--${x.group}`}>{x.status}</span></td><td><strong>{x.finance_status}</strong><small className="muted">{x.erp_status}</small></td></tr>)}</tbody></table></div>}
    <p className="muted">Kaspi подтверждает статусы заказа, но не банковское зачисление. Для WB финансовая строка означает наличие строки отчёта реализации, а не подтверждение выплаты банком.</p>
  </section>;
}

function ClientMarketplaceReport({channel,ctx,accounts,selectedAccount}) {
  const [start,setStart]=useState(ctx.start), [end,setEnd]=useState(ctx.end);
  const [range,setRange]=useState(null), [refresh,setRefresh]=useState(0), [busy,setBusy]=useState(false), [error,setError]=useState(""), [notice,setNotice]=useState("");
  const params=new URLSearchParams({channel,start:range?.start||start,end:range?.end||end});
  if(ctx.company) params.set("company_id",ctx.company);
  if(selectedAccount) params.set("account_id",String(selectedAccount.id));
  const active=Boolean(range);
  const summary=useLoad(channel==="Kaspi"&&active?"/marketplace-summary?"+params:null,refresh);
  const salesParams=new URLSearchParams(params); salesParams.set("metric","sales");
  const returnsParams=new URLSearchParams(params); returnsParams.set("metric","returns");
  const sales=useLoad(channel==="Kaspi"&&active?"/marketplace-record-details?"+salesParams:null,refresh);
  const returns=useLoad(channel==="Kaspi"&&active?"/marketplace-record-details?"+returnsParams:null,refresh);
  const apiAvailable=summary.data?.api_data_available===true;
  const generate=async(event)=>{
    event.preventDefault(); setError(""); setNotice("");
    if(!start||!end||end<start){setError("Проверьте даты: начало должно быть не позже окончания.");return;}
    setRange({start,end});
    setRefresh(v=>v+1);
    setNotice(channel==="Kaspi"
      ? "Загружаю уже сохранённые записи из базы. Выбор периода не запускает синхронизацию."
      : "Загружаю сохранённые данные за выбранный период.");
  };
  const download=async()=>{
    if(!range) return;
    setError(""); setBusy(true);
    try { await downloadApiFile(`/marketplace-report.xlsx?${params.toString()}`,`${channel}-API-${range.start}-${range.end}.xlsx`); }
    catch(e){setError(e.message||"Не удалось сформировать Excel");}
    finally{setBusy(false);}
  };
  const reportReady=channel!=="Kaspi"||(summary.data?.sync_status==="done"&&summary.data?.source_complete===true);
  return <section className="panel marketplace-client-report" aria-label={`Отдельный отчёт ${channel}`}>
    <div className="section-heading"><div><h3>Отдельный отчёт {channel}</h3><p className="muted">Для Kaspi это отчёт по заказам/позициям API, не финансовая выписка Kaspi Pay. Для точной сверки выплат, фактических возвратов и комиссии загрузите официальный XLSX через «Импорт → Отчёт маркетплейса».</p></div></div>
    <form className="row-actions" onSubmit={generate}>
      <label>С<input type="date" value={start} onChange={e=>setStart(e.target.value)} required/></label>
      <label>По<input type="date" value={end} onChange={e=>setEnd(e.target.value)} required/></label>
      <button className="primary" type="submit" disabled={busy||!accounts.length}>{busy?"Готовим…":"Показать отчёт"}</button>
      {channel==="Kaspi"&&<button type="button" disabled={!range||busy} onClick={download}>{busy?"Формируем…":"Скачать Excel"}</button>}
    </form>
    {error&&<ErrorBox error={error}/>}{notice&&<p className="muted" role="status" aria-live="polite">{notice}</p>}
    {active&&<>
      {channel==="Wildberries" ? <WBFinanceReport key={`client-custom:${range.start}:${range.end}`} accounts={selectedAccount?[selectedAccount]:accounts} company={ctx.company} period="custom" start={range.start} end={range.end}/> : <>
        {summary.loading&&!summary.data?<Spinner/>:summary.error?<ErrorBox error={summary.error}/>:<>
          {channel==="Kaspi"&&!reportReady&&<p className="muted" role="status"><strong>Предварительный отчёт.</strong> Отображены уже сохранённые данные за выбранный период. Суммы и количество могут измениться до завершения обхода API и подтверждения полноты.</p>}
          <p className="muted">Период {range.start} — {range.end} · синхронизация: {summary.data?.sync_status||"—"}. {summary.data?.sync_status==="running"?"Синхронизация идёт в фоне; файл содержит уже сохранённые строки и является предварительным.":summary.data?.sync_status==="paused"?"Фоновая загрузка остановлена; показаны сохранённые строки. Полнота отчёта не подтверждена.":summary.data?.source_complete?"Обход API завершён для настроенного окна истории; обязательные данные проверены.":"Источник пока не подтверждён как полный; показаны сохранённые записи."}</p>
          {summary.data?.source_quality?.progress?.map(p=><p className="muted" key={p.account_id}>Магазин #{p.account_id}: пакетов {p.batches}; страниц списка API {p.order_list_pages}; получено записей заказов {p.order_records_received} (с повторами между статусами); позиций {p.order_entries}. {p.scan_from&&`История с ${p.scan_from}; текущая граница ${p.scan_through}.`} {p.state&&`Статус ${p.state}, страница ${p.page+1}${p.page_count?` из ${p.page_count}`:""}, пакет ${p.offset||0}/${p.page_size||"—"}.`}</p>)}
          {summary.data?.source_quality&&!summary.data.source_quality.data_complete&&<p role="status">Требуется сверка: заказов с неполным составом — {summary.data.source_quality.issues.missing_entries}; без даты выдачи — {summary.data.source_quality.issues.missing_completion_date}; возвратов без даты — {summary.data.source_quality.issues.missing_return_date}; обратных доставок без даты возврата — {summary.data.source_quality.issues.missing_return_delivery_date}; некорректных позиций — {summary.data.source_quality.issues.invalid_lines}; без кода товара — {summary.data.source_quality.issues.missing_product_identity}; позиций без заказа — {summary.data.source_quality.issues.orphan_entries}. Недостающие даты возвратов нужно подтвердить отчётом Kaspi; дата продажи вместо них не используется.</p>}
          <div className="marketplace-report-summary">
        {[ ["Продажи API",apiAvailable?summary.data?.api_gross_revenue:null], ["Продажи после возвратов",apiAvailable?summary.data?.api_revenue:null], ["Единиц продано",!apiAvailable?"Нет данных":summary.data?.api_units==null?"—":`${summary.data.api_units} шт.`], ["Возвраты",!apiAvailable?"Нет данных":summary.data?.api_returns==null?"—":summary.data.api_returns], ["Доставка продавца API",!apiAvailable?"Нет данных":summary.data?.api_logistics==null?"—":summary.data.api_logistics], ["Обратная доставка API",!apiAvailable?"Нет данных":summary.data?.api_return_logistics==null?"—":summary.data.api_return_logistics], ["Возвращённые единицы без даты",!apiAvailable?"Нет данных":`${summary.data?.api_undated_return_units||0} шт.`], ["Единиц возврата",!apiAvailable?"Нет данных":summary.data?.api_return_units==null?"—":`${summary.data.api_return_units} шт.`] ].map(([label,value])=><article className="kpi" key={label}><span>{label}</span><strong>{typeof value==="number"?money(value):value??"Нет подтверждённых данных"}</strong></article>)}
          </div>
          <h4>Финансовая оценка QOR · KZT</h4>
          <div className="marketplace-report-summary">
            {[
              ["К перечислению · оценка", apiAvailable ? summary.data?.kaspi_estimated_proceeds : null, "Расчёт QOR, не подтверждение выплаты Kaspi Pay."],
              ["Комиссия · учтено / оценка", summary.data?.commission || summary.data?.commission_estimated ? summary.data.commission : null, summary.data?.commission_estimated ? "Оценка модели: " + money(summary.data.commission_estimated) + "." : "Показывает только учтённые в QOR расходы."],
              ["Логистика · учтено", summary.data?.logistics ? summary.data.logistics : null, "Уже сохранённые расходы QOR."],
              ["Обратная логистика · учтено", summary.data?.return_logistics ? summary.data.return_logistics : null, "Уже сохранённые расходы QOR."],
              ["Реклама · учтено", summary.data?.advertising ? summary.data.advertising : null, "Уже сохранённые расходы QOR."],
              ["Прибыль QOR", summary.data?.net_profit, summary.data?.financial_complete ? "Текущий расчёт финансового ядра QOR." : "Предварительно: источник или затраты ещё не подтверждены."],
              ["Штрафы · учтено в QOR", summary.data?.marketplace_fines, "Kaspi API заказов штрафы не передаёт. Здесь только уже внесённые в QOR расходы категории «штраф/fine»."]
            ].map(([label,value,note])=><article className="kpi" key={label}><span>{label}</span><strong>{typeof value==="number"?money(value):value??"Нет подтверждённых данных"}</strong><small>{note}</small></article>)}
          </div>
          <p className="muted">Предварительные показатели обновляются по мере поступления API-строк. Даты и суммы фактических возвратов, банковские выплаты и не загруженные штрафы нельзя подтвердить этим API-отчётом.</p>
          {summary.data?.sync_errors?.length>0&&<ErrorBox error={summary.data.sync_errors.join("; ")}/>}
          <p className="muted">Kaspi API подтверждает позиции и статусы возвратов, но не отдаёт фактические дату и сумму возврата. Поэтому неподтверждённые суммы в отчёте остаются пустыми.</p>
          {sales.loading?<Spinner/>:sales.error?<ErrorBox error={sales.error}/>:<><h4>Продажи API · {sales.data?.items?.length||0} строк</h4><div className="table-wrap"><table className="data-table"><thead><tr><th>Дата выдачи</th><th>Магазин</th><th>ID заказа</th><th>Товар / SKU</th><th>Кол-во</th><th>Сумма API</th><th>Статус</th></tr></thead><tbody>{(sales.data?.items||[]).slice(0,1000).map(x=><tr key={`${x.account_id}:${x.id}`}><td>{x.event_date||"—"}</td><td>{x.store}</td><td>{x.reference}</td><td>{x.product_name}<small>{x.sku}</small></td><td>{x.quantity??"—"}</td><td>{x.amount==null?"—":money(Number(x.amount)*100)}</td><td>{x.status}</td></tr>)}</tbody></table></div></>}
          {returns.loading?<Spinner/>:returns.error?<ErrorBox error={returns.error}/>:<><h4>Возвраты API · {returns.data?.items?.length||0} строк</h4><div className="table-wrap"><table className="data-table"><thead><tr><th>Дата API</th><th>Магазин</th><th>ID заказа</th><th>Товар / SKU</th><th>Кол-во</th><th>Сумма</th><th>Статус</th></tr></thead><tbody>{(returns.data?.items||[]).slice(0,1000).map(x=><tr key={`${x.account_id}:${x.id}`}><td>{x.event_date||"Не подтверждена"}</td><td>{x.store}</td><td>{x.reference}</td><td>{x.product_name}<small>{x.sku}</small></td><td>{x.quantity??"—"}</td><td>{x.amount==null?"Не предоставлена API":money(Number(x.amount)*100)}</td><td>{x.status}</td></tr>)}</tbody></table></div></>}
        </>}
      </>}
    </>}
  </section>;
}

function MarketplaceInbox({ channel, ctx }) {
  const [wbTab,setWbTab] = useState("finance");
  const [showClientReport,setShowClientReport]=useState(false);
  const [ordersMode,setOrdersMode] = useState(false);
  const [kaspiReportMode,setKaspiReportMode] = useState("issued");
  const [summaryReload,setSummaryReload] = useState(0);
  const [kpiDetail,setKpiDetail] = useState(null);
  const kaspiAutoSyncRef = useRef(new Set());
  const kaspiLastRefreshRef = useRef(ctx.refresh);

  const [showTechnical,setShowTechnical] = useState(false);
  const selectedAccountId = ctx.marketplaceAccountId || "";
  const [offset,setOffset] = useState(0), [status,setStatus] = useState(""),
    [selected,setSelected] = useState(null), [product,setProduct] = useState(""),
    [key,setKey] = useState(""), [error,setError] = useState(""), [busy,setBusy] = useState(false),
    [currency,setCurrency] = useState("RUB"), [rate,setRate] = useState(""), [rateDate,setRateDate] = useState(today());
  const accounts = (ctx.refs.accounts || []).filter(a=>a.active !== false && a.channel===channel && (!ctx.company || String(a.company_id)===String(ctx.company)));
  const selectedAccount = accounts.find(a=>String(a.id)===String(selectedAccountId));
  const scopedAccounts = selectedAccount ? [selectedAccount] : accounts;
  const params = new URLSearchParams({limit:"30", offset:String(offset), channel});
  if (ctx.company) params.set("company_id", ctx.company);
  if (selectedAccount) params.set("account_id", String(selectedAccount.id));
  if (status) params.set("status",status);
  const state = useLoad("/marketplace-records?" + params, ctx.refresh);
  const summaryParams = new URLSearchParams({channel, start:ctx.start, end:ctx.end});
  if (ctx.company) summaryParams.set("company_id", ctx.company);
  if (selectedAccount) summaryParams.set("account_id", String(selectedAccount.id));
  const summaryPath = "/marketplace-summary?" + summaryParams;
  const summary = useLoad(summaryPath, `${ctx.refresh}:${summaryReload}`);
  const summaryCacheRef = useRef({path:"", data:null});
  useEffect(()=>{
    if (summary.data) summaryCacheRef.current = {path:summaryPath, data:summary.data};
  },[summary.data,summaryPath]);
  const displayedSummary = summary.data || (summary.loading && summaryCacheRef.current.path === summaryPath ? summaryCacheRef.current.data : null);
  const canSyncKaspi = can(ctx.auth,"accounts",true);
  const accountKey = scopedAccounts.map(a=>a.id).join(",");
  const ordersCreatedParams = new URLSearchParams({start:ctx.start,end:ctx.end,limit:"100"});
  if (ctx.company) ordersCreatedParams.set("company_id",ctx.company);
  if (selectedAccount) ordersCreatedParams.set("account_id", String(selectedAccount.id));
  const ordersCreated = useLoad(channel === "Kaspi" && kaspiReportMode === "created" ? "/kaspi/orders-created?" + ordersCreatedParams : null, `${ctx.refresh}:${summaryReload}`);
  useEffect(()=>{
    if (channel !== "Kaspi" || !accountKey || !canSyncKaspi || summary.loading || !summary.data) return;
    const forceSync = ctx.refresh !== kaspiLastRefreshRef.current;
    kaspiLastRefreshRef.current = ctx.refresh;
    const key = `${accountKey}:${ctx.start}:${ctx.end}:${kaspiReportMode}:${ctx.refresh}`;
    if (kaspiAutoSyncRef.current.has(key)) return;
    kaspiAutoSyncRef.current.add(key);
    // Read the saved report first; start one background pull afterwards. Do not
    // refetch the full report or retry the sync from the display loop.
    accountKey.split(",").filter(Boolean).forEach(id =>
      api(`/accounts/${id}/sync-kaspi-period?start=${encodeURIComponent(ctx.start)}&end=${encodeURIComponent(ctx.end)}&report_mode=${kaspiReportMode}&force=${forceSync}`,{method:"POST",timeoutMs:10000}).catch(()=>{})
    );
  },[channel,accountKey,canSyncKaspi,ctx.start,ctx.end,ctx.refresh,kaspiReportMode,summary.loading,summary.data]);
  const m = displayedSummary || {};
  const created = ordersCreated.data || {};
  const activeSyncErrors = kaspiReportMode === "created" ? created.sync_errors : m.sync_errors;
  useEffect(()=>{
    const localToday=today();
    const yesterday=new Date(`${localToday}T00:00:00Z`); yesterday.setUTCDate(yesterday.getUTCDate()-1);
    const yesterdayKey=yesterday.toISOString().slice(0,10);
    if(channel!=="Kaspi" || kaspiReportMode!=="issued" || !canSyncKaspi || ctx.start!==ctx.end || ![localToday,yesterdayKey].includes(ctx.end)) return;
    const interval=ctx.end===localToday?5*60*1000:10*60*1000;
    const timer=window.setInterval(()=>{
      Promise.allSettled(accountKey.split(",").filter(Boolean).map(id=>api(`/accounts/${id}/sync-kaspi-period?start=${encodeURIComponent(ctx.start)}&end=${encodeURIComponent(ctx.end)}&report_mode=issued`,{method:"POST",timeoutMs:10000})))
        .then(()=>setSummaryReload(v=>v+1));
    },interval);
    return ()=>window.clearInterval(timer);
  },[channel,kaspiReportMode,canSyncKaspi,accountKey,ctx.start,ctx.end]);
  const productParams = new URLSearchParams({channel, limit:"60", start:ctx.start, end:ctx.end});
  if (ctx.company) productParams.set("company_id", ctx.company);
  if (selectedAccount) productParams.set("account_id", String(selectedAccount.id));
  const marketplaceProducts = useLoad("/marketplace-products?" + productParams, ctx.refresh);
  const wbReportRange = (() => {
    if (channel !== "Wildberries") return null;
    const todayKey = today();
    const asDate = value => new Date(`${value}T00:00:00Z`);
    const shift = (value, days) => {
      const d = asDate(value);
      d.setUTCDate(d.getUTCDate() + days);
      return d.toISOString().slice(0, 10);
    };
    const yesterdayKey = shift(todayKey, -1);
    let reportEnd = ctx.end;
    if (ctx.start === ctx.end && ctx.end === todayKey) {
      return {error:"Финансовые строки WB доступны после закрытия дня. Выберите «Вчера» или завершённый период."};
    }
    if (ctx.end === todayKey && ctx.start.slice(0, 7) === todayKey.slice(0, 7) && ctx.start.endsWith("-01")) {
      reportEnd = yesterdayKey;
    }
    if (ctx.start === reportEnd && reportEnd < todayKey) {
      return {period:"daily", start:ctx.start, end:reportEnd};
    }
    const startDate = asDate(ctx.start);
    if (startDate.getUTCDay() === 1 && shift(ctx.start, 6) === reportEnd && reportEnd < todayKey) {
      return {period:"weekly", start:ctx.start, end:reportEnd};
    }
    const nextMonth = new Date(Date.UTC(startDate.getUTCFullYear(), startDate.getUTCMonth() + 1, 1));
    const lastDay = new Date(nextMonth.getTime() - 86400000).toISOString().slice(0, 10);
    const sameMonth = reportEnd.slice(0, 7) === ctx.start.slice(0, 7);
    if (startDate.getUTCDate() === 1 && sameMonth && reportEnd < todayKey && (reportEnd === lastDay || reportEnd === yesterdayKey)) {
      return {period:"monthly", start:ctx.start, end:reportEnd};
    }
    if (reportEnd < todayKey) return {period:"custom", start:ctx.start, end:reportEnd};
    return {error:"Финансовый отчёт WB доступен только по завершённые дни. Укажите дату окончания не позже вчерашнего дня."};
  })();

  useEffect(()=>setOffset(0), [ctx.company,channel,status,selectedAccountId]);
  const run = async (fn) => { setBusy(true);setError("");try{await fn();}catch(e){setError(e.message);}finally{setBusy(false);} };
  const bind = () => run(async()=>{
    const r = await api(`/marketplace-records/${selected.id}/mapping`,{method:"POST",body:{product_id:Number(product),external_keys:[key]}});
    ctx.notify(`Проведено ${r.projected}; ожидает обработки ${r.pending_erp}`);setSelected(null);
  });
  const incomplete = m.financial_complete === false;
  const fxPending = Number(m.api_unconverted || 0);
  const marketplaceKpis = [
    [channel === "Wildberries" ? "Оборот продаж WB" : channel === "Kaspi" ? "Выручка API за вычетом возвратов" : "Продажи API", channel === "Kaspi" ? (m.api_revenue == null ? "Нет подтверждённых данных" : m.api_revenue) : (m.api_revenue ?? m.revenue), fxPending ? (channel === "Kaspi" ? `${fxPending} записей API пропущено: проверьте дату или сумму` : `${fxPending} операций ожидают курс`) : (channel === "Wildberries" ? "Отдельный отчёт продаж за выбранный период" : channel === "Kaspi" ? "Выручка по дате выдачи минус возвраты по дате возврата" : "Подтверждённая выручка непосредственно из API"), {source:"api",metric:"sales",title:"Детализация продаж API"}],
    ...(channel === "Kaspi" ? [["Возвраты API", m.api_returns == null ? "—" : m.api_returns, `${m.api_return_units == null ? "—" : m.api_return_units} шт. за выбранный период`, {source:"api",metric:"returns",title:"Возвраты Kaspi по данным API"}], ["Доставка API по выданным заказам", m.api_logistics == null ? "—" : m.api_logistics, `${m.api_logistics_rows||0} строк deliveryCostForSeller по дате выдачи`, {source:"api",metric:"logistics",title:"Доставка продавца по Kaspi API"}], ["Возвращённые единицы без даты", `${m.api_undated_return_units||0} шт.`, "Kaspi API не дал дату возврата; строки не отнесены к выбранному периоду", {source:"api",metric:"returns",title:"Возвраты без даты Kaspi API"}]] : []),
    ["Продано", m.api_units == null ? "—" : `${m.api_units} шт`, "Количество продаж за выбранный период за вычетом возвращённых единиц", {source:"api",metric:"sales",title:"Продажи API по товарам и магазинам"}],
    ...(channel === "Wildberries" ? [["К перечислению по отчёту", (m.settlement_rows > 0 ? m.settlement_accrued : "Нет данных отчёта"), m.settlement_unconverted ? `${m.settlement_unconverted} строк ожидают курс` : (m.settlement_rows > 0 ? "Начислено по финансовому отчёту; не банковская выплата" : "Загрузите недельный отчёт WB; ноль не означает отсутствие начислений"), {source:"api",metric:"settlement",title:"Строки начисления WB"}]] : []),
    ["Проведено в ERP", m.revenue, m.pending_sales ? `${m.pending_sales} продаж проведены, но ожидают себестоимость FIFO` : "Финансовые продажи, уже проведённые в ERP", {source:"ledger",metric:"revenue",title:"Проведённые продажи ERP"}],
    ["Себестоимость FIFO", incomplete ? "—" : m.cogs, incomplete ? "Будет рассчитана после наличия себестоимости/партий" : "Только проведённые продажи", {source:"ledger",metric:"cogs",title:"Себестоимость FIFO"}],
    ["Комиссия", m.commission, channel === "Kaspi" && Number(m.commission_estimated || 0) > 0 ? `Расчётная ставка ${Math.round(Number(m.commission_rate || 0) * 100)}% по настройке; не фактическая комиссия Kaspi` : "Расход маркетплейса", {source:"ledger",metric:"commission",title:"Комиссия по проведённым операциям"}],
    ["Логистика продавца", m.logistics, "Стоимость доставки за счёт продавца; доставка покупателя не вычитается", {source:"ledger",metric:"logistics",title:"Логистика по проведённым операциям"}],
    ...(channel === "Kaspi" ? [["Доставка возврата", m.return_logistics, "Отдельный расход возврата, если он пришёл из API или импорта", {source:"ledger",metric:"expenses",title:"Расшифровка расходов, включая доставку возврата"}], ["К получению (расчёт)", m.kaspi_estimated_proceeds, "Выданные продажи − комиссия Kaspi − доставка продавца − доставка возврата; не банковская выплата", {source:"api",metric:"logistics",title:"Данные API для расчётного итога"}]] : []),
    ["Реклама", m.advertising, "Расход маркетплейса", {source:"ledger",metric:"advertising",title:"Расходы на рекламу"}],
    ["Чистая прибыль", incomplete ? "—" : m.net_profit, incomplete ? (fxPending ? "Прибыль ожидает курс/проведение и FIFO — ложное значение не показываем" : "Не показываем ложную прибыль: есть продажи без FIFO") : (m.margin == null ? "Маржа —" : `Маржа ${decimal(m.margin)}%`), {source:"ledger",metric:"net_profit",title:"Чистая прибыль по проведённым операциям"}],
  ];
  return <div className="panel marketplace-inbox">
    <div className="section-heading"><div><h3>{channel} · результат бизнеса</h3><p className="muted">{ctx.start} — {ctx.end}. Цифры берутся из того же финансового ядра, что Dashboard, отчёты и AI.</p></div><div className="row-actions"><button type="button" className="secondary" onClick={()=>{ctx.setMarketplaceReportChannel(channel);ctx.navigate("marketplace-product-report");}}>Сводный отчёт по SKU</button><button type="button" className={showClientReport?"primary":""} aria-expanded={showClientReport} onClick={()=>setShowClientReport(v=>!v)}>{showClientReport?"Скрыть отдельный отчёт":"Отчёт за период · Excel"}</button>{state.loading ? <span className="pill" role="status" aria-live="polite">Загружаем API…</span> : state.error ? <span className="pill marketplace-read-error" role="alert" title={state.error}>Ошибка чтения API</span> : <span className="pill">{state.data?.total ?? 0} API-записей</span>}</div></div>
    {showClientReport&&<ClientMarketplaceReport channel={channel} ctx={ctx} accounts={scopedAccounts} selectedAccount={selectedAccount}/>}
    {(channel === "Kaspi" || channel === "Wildberries") && <div className="row-actions" role="group" aria-label="Отчёты маркетплейса"><button type="button" className={!ordersMode?"primary":""} aria-pressed={!ordersMode} onClick={()=>setOrdersMode(false)}>Продажи и финансы</button><button type="button" className={ordersMode?"primary":""} aria-pressed={ordersMode} onClick={()=>setOrdersMode(true)}>Заказы и доставка</button></div>}
    {ordersMode ? <MarketplaceOrdersReport channel={channel} ctx={ctx} accounts={scopedAccounts} selectedAccount={selectedAccount} canRefresh={can(ctx.auth,"accounts",true)}/> : <>
    {channel === "Kaspi" && <div className="row-actions kaspi-report-controls" role="group" aria-label="Режим отчёта Kaspi">
      <button type="button" className={kaspiReportMode==="issued"?"primary":""} aria-pressed={kaspiReportMode==="issued"} onClick={()=>setKaspiReportMode("issued")}>Продажи по дате выдачи</button>
      <button type="button" className={kaspiReportMode==="created"?"primary":""} aria-pressed={kaspiReportMode==="created"} onClick={()=>setKaspiReportMode("created")}>Заказы по дате создания</button>

      <span className="muted">Последняя попытка: {(kaspiReportMode==="created"?created.last_sync:m.last_sync)?new Date(kaspiReportMode==="created"?created.last_sync:m.last_sync).toLocaleString("ru-RU"):"нет данных"}</span>
    </div>}
    {channel === "Kaspi" && activeSyncErrors?.length ? <p className="error-box" role="alert">Синхронизация не подтверждена. Показаны сохранённые данные, если они есть. {activeSyncErrors.join("; ")}</p> : null}
    {channel === "Kaspi" && kaspiReportMode === "created" ? <>
      {ordersCreated.loading ? <Spinner/> : ordersCreated.error ? <ErrorBox error={ordersCreated.error}/> : <>
        <p className="muted">Созданные заказы за период. Сумма заказов не является выручкой или суммой к перечислению. {created.sync_status==="running"?"Обновляются данные API…":!created.api_data_available?"Нет подтверждённого ответа API для этого периода.":""}</p>
        <div className="table-scroll"><table><thead><tr><th>Дата создания</th><th>Заказ</th><th>Статус</th><th>Единиц</th><th>Сумма заказа</th></tr></thead><tbody>
          {(created.items||[]).map(x=><tr key={`${x.account_id}:${x.order_id}`}><td>{x.created_date}</td><td>{x.order_id}</td><td>{x.status}</td><td>{x.units}</td><td>{x.amount==null?"—":money(Number(x.amount)*100)}</td></tr>)}
          <tr><th colSpan="3">Итого по выбранной странице: {created.api_data_available?(created.total||0):"—"} заказов</th><th>{created.api_data_available?(created.items||[]).reduce((n,x)=>n+Number(x.units||0),0):"—"}</th><th>{created.orders_amount==null?"—":money(Number(created.orders_amount)*100)}</th></tr>
        </tbody></table></div>
      </>}
    </> : null}
    {channel === "Kaspi" && m.sync_in_progress && !m.sync_errors?.length && kaspiReportMode === "issued" && <p className="muted" role="status">Обновляем выбранный период Kaspi в фоне. Страница продолжает показывать сохранённые итоги.</p>}
    {channel === "Wildberries" && <div className="wb-report-tabs" role="tablist" aria-label="Раздел Wildberries">{[["daily","Продажи"],["finance","Финансы"],["products","Товары"]].map(([id,label])=><button type="button" role="tab" aria-selected={wbTab===id} className={wbTab===id?"active":""} key={id} onClick={()=>setWbTab(id)}>{label}</button>)}</div>}
    {(channel !== "Wildberries" || wbTab === "daily") && !(channel === "Kaspi" && kaspiReportMode === "created") && (summary.loading && !displayedSummary ? <Spinner/> : summary.error ? <ErrorBox error={summary.error}/> : (() => {
      const visible = marketplaceKpis.filter(([title])=>channel!=="Wildberries" || ["Оборот продаж WB","Продано"].includes(title));
      const isPrimary = ([title]) => channel==="Kaspi"
        ? ["Выручка API за вычетом возвратов","К получению (расчёт)","Продано","Чистая прибыль"].includes(title)
        : channel==="Wildberries" ? ["Оборот продаж WB","Продано"].includes(title)
        : ["Продажи API","Продано","Чистая прибыль"].includes(title);
      const renderMetric = ([title,value,note,detail]) => <button type="button" className={"kpi marketplace-kpi-button "+(title==="Чистая прибыль"?"featured":"")} key={title} onClick={()=>setKpiDetail({...detail,channel,account_id:selectedAccount?.id,store:selectedAccount?.name})} title="Открыть расшифровку по магазину">
        <div><span>{title}</span></div><strong>{typeof value==="number"?money(value):value}</strong>{note&&<small>{note}</small>}
      </button>;
      return <>
        {channel === "Kaspi" ? (() => {
          const totalMetric = visible.find(([title]) => title === "К получению (расчёт)");
          const summaryMetrics = visible.filter(item => isPrimary(item) && item !== totalMetric);
          return <div className="kaspi-report-overview">
            {totalMetric && <button type="button" className="kaspi-report-total" onClick={()=>setKpiDetail({...totalMetric[3],channel,account_id:selectedAccount?.id,store:selectedAccount?.name})} title="Открыть расшифровку расчёта">
              <span>{totalMetric[0]}</span>
              <strong>{typeof totalMetric[1]==="number"?money(totalMetric[1]):totalMetric[1]}</strong>
              <small>{totalMetric[2]}</small>
            </button>}
            <div className="kaspi-report-summary">{summaryMetrics.map(renderMetric)}</div>
          </div>;
        })() : <div className="marketplace-report-summary">{visible.filter(isPrimary).map(renderMetric)}</div>}
        {visible.some(item=>!isPrimary(item))&&<details className="marketplace-report-details marketplace-report-more">
          <summary><span>Расшифровка продаж и расходов</span><small>Комиссии, логистика и прибыль</small></summary>
          <div className="marketplace-report-metrics">{visible.filter(item=>!isPrimary(item)).map(renderMetric)}</div>
        </details>}
      </>;
    })())}
    {channel === "Wildberries" && wbTab === "finance" && (wbReportRange?.period ? <WBFinanceReport key={`${wbReportRange.period}:${wbReportRange.start}:${wbReportRange.end}`} accounts={scopedAccounts} company={ctx.company} {...wbReportRange}/> : <div className="info-banner wb-report-range-note" role="status">{wbReportRange?.error}</div>)}
    {(channel !== "Wildberries" || wbTab === "products") && <><div className="section-heading"><div><h3>Товары маркетплейса</h3><p className="muted">Продажи и прибыль связаны с товаром QOR по SKU. Себестоимость и остаток меняются в единой карточке «Товары / SKU».</p></div><span className="pill">{marketplaceProducts.data?.total || 0} товаров</span></div>
    {marketplaceProducts.error ? <ErrorBox error={marketplaceProducts.error}/> : marketplaceProducts.loading ? <Spinner/> : <div className="marketplace-product-grid">
      {(marketplaceProducts.data?.items || []).slice(0,60).map(p=><MarketplaceProductCard key={p.id} p={p} channel={channel}/>)}
    </div>}
    </>}
    {channel === "Wildberries" && <button type="button" className="wb-tech-toggle" onClick={()=>setShowTechnical(v=>!v)}>{showTechnical ? "Скрыть технические данные" : "Технические данные API (для администратора)"}</button>}
    {(channel !== "Wildberries" || showTechnical) && <><div className="section-heading marketplace-technical"><div><h3>Технические данные API</h3><p className="muted">Исходные записи нужны для сверки и диагностики. Они сами по себе не считаются продажами или расходами.</p></div></div>
    <div className="row-actions">{can(ctx.auth,"accounts",true) && <button disabled={busy} onClick={()=>run(async()=>{const result=await api("/admin/reconcile-marketplaces",{method:"POST"});ctx.notify(`Проверено аккаунтов: ${result.results.length}. Данные ERP обновлены.`);})}>Восстановить учёт из сохранённых API-записей</button>}<select aria-label="Статус обработки" value={status} onChange={e=>setStatus(e.target.value)}><option value="">Все записи</option><option value="pending">Ожидают обработки</option><option value="projected">Проведены</option><option value="received_stock">Остатки для сверки</option></select>
      {scopedAccounts.map(a=><button key={a.id} disabled={busy} onClick={()=>run(async()=>{const r=await api(`/accounts/${a.id}/reprocess`,{method:"POST"});ctx.notify(`${a.name}: проведено ${r.projected}; ожидает ${r.pending_erp}`);})}>Обработать повторно: {a.name}</button>)}
    </div>
    {channel!=="Kaspi" && <div className="row-actions"><label>Дата курса<input type="date" value={rateDate} onChange={e=>setRateDate(e.target.value)}/></label><label>Валюта источника<select value={currency} onChange={e=>setCurrency(e.target.value)}><option>RUB</option><option>KZT</option></select></label><label>Курс в ₸ за 1 единицу<input type="number" min="0.0001" step="0.0001" value={rate} onChange={e=>setRate(e.target.value)}/></label>{accounts.map(a=><button key={a.id} disabled={busy || !rate || Number(rate)<=0} onClick={()=>run(()=>api(`/accounts/${a.id}/settlement`,{method:"PUT",body:{currency,effective_date:rateDate,fx_rate:Math.round(Number(rate)*10000)}}))}>Сохранить курс: {a.name}</button>)}</div>}
    <ErrorBox error={error || state.error}/>
    {state.loading ? <Spinner/> : <Table raw rows={state.data?.items || []} cols={["reference","product_name","sku","quantity","amount","currency","marketplace_status","status","stage_status","projection_reason"]} actions={row=>row.external_keys?.length && !["mapped_product","projected"].includes(row.status) && can(ctx.auth,"accounts",true) ? <button disabled={busy} onClick={()=>{setSelected(row);setKey(row.external_keys[0]);setProduct("");}}>Привязать товар</button> : null}/>}
    {selected && <div className="panel"><h3>Привязка товара</h3><label>Идентификатор источника<select value={key} onChange={e=>setKey(e.target.value)}>{selected.external_keys.map(k=><option key={k}>{k}</option>)}</select></label><label>Товар ERP<select value={product} onChange={e=>setProduct(e.target.value)}><option value="">Выберите товар</option>{(ctx.refs.products || []).map(p=><option value={p.id} key={p.id}>{p.sku} · {p.name}</option>)}</select></label><button className="primary" disabled={busy || !product} onClick={bind}>Сохранить привязку</button><button onClick={()=>setSelected(null)}>Закрыть</button></div>}
    <div className="row-actions"><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-30))}>Предыдущие</button><span>{offset+1}–{Math.min(offset+30,state.data?.total || 0)}</span><button disabled={offset+30 >= (state.data?.total || 0)} onClick={()=>setOffset(offset+30)}>Следующие</button></div>
    </>}
    </>}
    {kpiDetail && (kpiDetail.source === "api" ? <MarketplaceRecordDetails ctx={ctx} detail={kpiDetail} onClose={()=>setKpiDetail(null)}/> : <ReportDetails ctx={ctx} detail={{...kpiDetail,account_id:selectedAccount?.id}} onClose={()=>setKpiDetail(null)}/>)}
  </div>;
}

function DataPage({ page, ctx }) {
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
  const entity = page === "marketplace-products" ? "products" : channels.includes(page) ? "sales" : page;
  const [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [integration, setIntegration] = useState(null),
    [integrationForm, setIntegrationForm] = useState({token:"",client_id:"",api_key:""}),
    [integrationSettings, setIntegrationSettings] = useState({}),
    [wbWarehouses, setWbWarehouses] = useState([]),
    [kaspiFeedUrl, setKaspiFeedUrl] = useState(""),
    [selectedProducts, setSelectedProducts] = useState([]),
    [productMatchResult, setProductMatchResult] = useState(null),
    [productCatalogJob, setProductCatalogJob] = useState(null),
    [productOperation, setProductOperation] = useState(null),
    [catalogCategory, setCatalogCategory] = useState(""),
    [catalogSort, setCatalogSort] = useState("name"),
    [catalogLinkFilter, setCatalogLinkFilter] = useState("all"),
    [kaspiAction, setKaspiAction] = useState({order_id:"",code:"",status:"ACCEPTED_BY_MERCHANT",cancellation_reason:"BUYER_CANCELLATION_BY_MERCHANT",cancellation_comment:"",number_of_space:"1",security_code:""});
  const mutationLock = useRef(false);
  const run = async (fn) => { setBusy(true); setError(""); try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  const params = new URLSearchParams({
    limit: "30",
    offset: String(offset),
    search,
  });
  if (ctx.company) params.set("company_id", ctx.company);
  if (channels.includes(page)) params.set("channel", page);
  if (["sales", "expenses", "cash", "purchases"].includes(entity)) {
    params.set("start", ctx.start);
    params.set("end", ctx.end);
  }
  if (entity === "products") {
    params.set("start", ctx.start || today().slice(0, 8) + "01");
    params.set("end", ctx.end || today());
    params.set("catalog_kind", page === "marketplace-products" ? "marketplace" : "master");
  }
  const state = useLoad("/data/" + entity + "?" + params, ctx.refresh);
  useEffect(() => setOffset(0), [search, ctx.company, ctx.start, ctx.end]);
  const cap = flat.find((x) => x[0] === page)?.[3];
  const writable =
    can(ctx.auth, cap, true) &&
    (!["companies", "users"].includes(entity) ||
      ctx.auth.user.role === "Owner");
  const openSale = (channel = "Offline") => {
    const account = (ctx.refs.accounts || []).find(a => a.channel === channel && (!ctx.company || a.company_id == ctx.company));
    if (!account) {
      ctx.open("accounts", {company_id:ctx.company || ctx.refs.companies?.[0]?.id || "", name:channel === "Offline" ? "Офлайн продажи" : "B2B продажи", channel});
      return;
    }
    ctx.open("sales", {account_id:account.id, company_id:ctx.company || account.company_id});
  };
  const remove = async (row) => {
    if (
      !confirm(
        entity === "accounts" ? `Отключить магазин «${row.name || row.id}»? Он исчезнет из текущих отчётов, история операций сохранится. Его можно подключить снова здесь.` : "Удалить запись «" + (row.name || row.id) + "»? Связанные с учётом записи удалить нельзя.",
      )
    )
      return;
    if (mutationLock.current) return;
    mutationLock.current = true;
    setBusy(true);
    try {
      await api("/data/" + entity + "/" + row.id, { method: "DELETE" });
      ctx.notify(entity === "accounts" ? "Магазин отключён; история сохранена" : "Запись удалена");
    } catch (e) {
      setError(e.message);
    } finally { mutationLock.current = false; setBusy(false); }
  };
  const saveProductPrice = async (product, price) => {
    const normalized = Math.round(Number(String(price).replace(",", ".")) * 100);
    if (!Number.isFinite(normalized) || normalized < 0) throw new Error("Введите корректную цену");
    const body = {version:product.version, description:product.description || "", barcode:product.barcode || "", purchase_cost:product.purchase_cost || 0, custom_fields:product.custom_fields || {}, marketplace_stock_allocations:product.marketplace_stock_allocations || {}, sku:product.sku, name:product.name, category:product.category || "", article:product.article || "", brand:product.brand || "", supplier:product.supplier || "", country:product.country || "", media:product.media || [], currency:product.currency || "KZT", fx_rate:product.fx_rate || 10000, weight_g:product.weight_g || 0, volume_cm3:product.volume_cm3 || 0, min_price:product.min_price || 0, recommended_price:product.recommended_price || 0, price:normalized, min_stock:product.min_stock || 0, active:product.active !== false, specifications:product.specifications || {}};
    await api(`/data/products/${product.id}`, {method:"PUT", body});
  };
  const quickPrice = async product => {
    setProductOperation({kind:"price", product});
  };
  const syncProductWB = async (product, accountId) => {
    if (!globalThis.confirm(`Отправить в WB цену ${money(product.price || 0)} и распределённые остатки для «${product.name}»?`)) return;
    setBusy(true); setError("");
    try {
      const result=await api(`/accounts/${accountId}/wb/products/${product.id}/sync`,{method:"POST",body:{confirm:true}});
      ctx.notify(`WB: задача цены отправлена; остаток обновлён (${result.stock_total} шт.)`);
    } catch(e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const bulkPrice = async () => {
    const rows = (state.data?.items || []).filter(p => selectedProducts.includes(p.id));
    if (!rows.length) return;
    const value = globalThis.prompt(`Новая цена для ${rows.length} товаров (₸)`);
    if (value == null) return;
    setBusy(true); setError("");
    let saved = 0;
    try {
      for (const product of rows) { await saveProductPrice(product, value); saved += 1; }
      setSelectedProducts([]); ctx.notify(`Цена сохранена для ${saved} товаров`);
    } catch(e) { setError(`Сохранено ${saved} из ${rows.length}. ${e.message}`); }
    finally { setBusy(false); }
  };
  const autoMatchProducts = () => run(async()=>{
    const result = await api("/products/marketplace-matching/auto", {method:"POST", body:ctx.company ? {company_id:Number(ctx.company)} : {}});
    setProductMatchResult(result);
    ctx.bump?.();
    ctx.notify(`Связано товаров с магазинами: ${result.products_linked}. Добавлено ID-связей: ${result.links_created}. Требуют проверки: ${result.review_count}. Магазинов с каталогом: ${result.catalog_accounts} из ${result.accounts_scanned}.`);
  });
  const loadWBProductCatalogs = () => run(async()=>{
    const result = await api("/products/marketplace-catalogs/wb/refresh", {method:"POST", body:ctx.company ? {company_id:Number(ctx.company)} : {}});
    setProductCatalogJob(result.job);
    ctx.notify(result.already_running ? "Загрузка каталога WB уже выполняется" : "Загрузка каталогов WB запущена; финансовые отчёты не пересчитываются");
  });
  const retryWBProductCatalogs = () => run(async()=>{
    const job = await api(`/jobs/${productCatalogJob.id}/retry`, {method:"POST"});
    setProductCatalogJob(job);
    ctx.notify("Повторная загрузка каталога WB запущена с сохранённого прогресса");
  });
  useEffect(()=>{
    if (!productCatalogJob?.id || !["queued","running"].includes(productCatalogJob.status)) return undefined;
    let live = true;
    const poll = async()=>{
      try {
        const job = await api(`/jobs/${productCatalogJob.id}`, {timeoutMs:10000});
        if (!live) return;
        setProductCatalogJob(job);
        if (["done","partial","failed"].includes(job.status)) {
          if (job.result?.per_account) setProductMatchResult({
            catalog_refresh: true,
            products_scanned: job.result.per_account.reduce((n,x)=>n+Number(x.catalog_items || 0),0),
            accounts_scanned: Object.keys(job.payload?.accounts || {}).length,
            catalog_accounts: job.result.per_account.filter(x=>Number(x.catalog_items || 0)>0).length,
            links_created: job.result.links_created || 0,
            products_linked: job.result.products_linked || 0,
            already_linked: 0,
            review: job.result.review || [], review_count: job.result.review_count || 0,
            per_account: job.result.per_account,
          });
          ctxRef.current.bump?.();
          ctxRef.current.notify(`Каталог WB: ${job.status === "done" ? "загружен" : job.status === "partial" ? "загружен частично" : "не загружен"}. Связано товаров с магазинами: ${job.result?.products_linked || 0}; проверить вручную: ${job.result?.review_count || 0}.${job.error ? ` ${job.error}` : ""}`);
        }
      } catch (e) { if (live) setError(e.message); }
    };
    const timer = window.setInterval(poll, 2500);
    poll();
    return ()=>{ live=false; window.clearInterval(timer); };
  },[productCatalogJob?.id,productCatalogJob?.status]);
  const catalogPageRows = state.data?.items || [];
  const catalogLinkCounts = {
    all: catalogPageRows.length,
    linked: catalogPageRows.filter(p=>productLinkSummary(p).complete).length,
    needs_link: catalogPageRows.filter(p=>productLinkSummary(p).needsLink > 0).length,
    error: catalogPageRows.filter(p=>productLinkSummary(p).errors > 0).length,
  };
  const catalogRows = [...catalogPageRows]
    .filter(p => !catalogCategory || p.category === catalogCategory)
    .filter(p => catalogLinkFilter === "all"
      || (catalogLinkFilter === "linked" && productLinkSummary(p).complete)
      || (catalogLinkFilter === "needs_link" && productLinkSummary(p).needsLink > 0)
      || (catalogLinkFilter === "error" && productLinkSummary(p).errors > 0))
    .sort((a,b) => catalogSort === "stock" ? (a.inventory?.available ?? 0)-(b.inventory?.available ?? 0)
      : catalogSort === "stock_desc" ? (b.inventory?.available ?? 0)-(a.inventory?.available ?? 0)
        : catalogSort === "price" ? (a.price || 0)-(b.price || 0)
          : String(a.name || "").localeCompare(String(b.name || ""), "ru"));
  const setReturnStatus = async (row, status) => {
    if (mutationLock.current) return;
    let reason;
    if (status === "defective" || status === "written_off") {
      reason = globalThis.prompt(status === "defective" ? "Причина брака" : "Причина списания");
      if (!reason || !reason.trim()) return;
    }
    mutationLock.current = true;
    setBusy(true);
    setError("");
    try {
      await api(`/returns/${row.id}/status`, { method: "POST", body: { status, reason } });
      ctx.notify(status === "restocked" ? "Возврат принят в пригодный остаток" : "Статус возврата обновлён");
    } catch (e) {
      setError(e.message);
    } finally {
      mutationLock.current = false;
      setBusy(false);
    }
  };
  const returnNext = (row) => ({
    requested: [["approved", "Одобрить"]],
    approved: [["in_transit", "Отправлен"]],
    in_transit: [["received", "Получен"]],
    received: [["inspection", "На проверку"]],
    inspection: [["restocked", "Пригоден: вернуть в остаток"], ["defective", "Брак"]],
    defective: [["written_off", "Списать"]],
  }[row.inventory_status || "requested"] || []);
  const openIntegration = async (row) => {
    setError("");
    try {
      const [st,settings] = await Promise.all([
        api(`/accounts/${row.id}/connection-status`),
        ["Kaspi","Wildberries"].includes(row.channel) ? api(`/accounts/${row.id}/marketplace-settings`) : Promise.resolve({})
      ]);
      setIntegration({...row, connection: st});
      setIntegrationForm({token:"",client_id:"",api_key:""});
      setIntegrationSettings(settings); setKaspiFeedUrl(""); setWbWarehouses([]);
    } catch(e) { setError(e.message); }
  };
  const saveMarketplaceSettings = async () => {
    setBusy(true); setError("");
    try {
      await api(`/accounts/${integration.id}/marketplace-settings`, {method:"PUT", body:integration.channel === "Kaspi" ? {
        kaspi_store_id:integrationSettings.kaspi_store_id || "",
        kaspi_merchant_id:integrationSettings.kaspi_merchant_id || "",
        kaspi_full_catalog_confirmed:!!integrationSettings.kaspi_full_catalog_confirmed,
        auto_sync:!!integrationSettings.auto_sync
      } : {wb_warehouse_id:integrationSettings.wb_warehouse_id || "",auto_sync:!!integrationSettings.auto_sync}});
      ctx.notify("Настройки синхронизации сохранены");
    } catch(e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const createKaspiFeedUrl = async () => {
    setBusy(true); setError("");
    try {
      const result=await api(`/accounts/${integration.id}/kaspi/feed-url`,{method:"POST"});
      setKaspiFeedUrl(result.feed_url); setIntegrationSettings({...integrationSettings,kaspi_feed_configured:true});
    } catch(e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const loadWBWarehouses = async () => {
    setBusy(true); setError("");
    try { const r=await api(`/accounts/${integration.id}/wb/warehouses`); setWbWarehouses(r.items || []); }
    catch(e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const saveIntegration = async () => {
    setBusy(true); setError("");
    try {
      const body = integration.channel === "Ozon" ? {client_id:integrationForm.client_id,api_key:integrationForm.api_key} : {token:integrationForm.token};
      await api(`/accounts/${integration.id}/credentials`, {method:"PUT", body, timeoutMs:15000});
      // Credential test is intentionally lightweight. Full history is loaded
      // only after the modal closes in the background.
      await api(`/accounts/${integration.id}/test-connection`,{method:"POST",timeoutMs:20000});
      setIntegrationForm({token:"",client_id:"",api_key:""});
      try {
        await api(`/accounts/${integration.id}/sync-now?background=true`, {method:"POST",timeoutMs:10000});
      } catch (syncError) {
        if (!String(syncError.message || "").includes("уже выполняется")) throw syncError;
      }
      setIntegration(null);
      ctx.bump?.();
      ctx.notify(`${integration.channel}: подключение проверено. Синхронизация запущена в фоне.`);
    } catch(e){setError(e.message)} finally {setBusy(false)}
  };
  const testIntegration = async () => {
    setBusy(true); setError("");
    try {
      const r=await api(`/accounts/${integration.id}/test-connection`,{method:"POST",timeoutMs:20000});
      ctx.notify(`${integration.channel}: подключение подтверждено. Проверено записей: ${r.records_checked ?? 0}`);
    } catch(e){setError(e.message)} finally{setBusy(false)}
  };
  const runKaspiAction = async () => {
    if (!kaspiAction.order_id.trim()) { setError("Укажите ID заказа Kaspi"); return; }
    if (!confirm(`Изменить реальный заказ Kaspi ${kaspiAction.code || kaspiAction.order_id} → ${kaspiAction.status}?`)) return;
    setBusy(true); setError("");
    try {
      const body={...kaspiAction,number_of_space:Number(kaspiAction.number_of_space||1)};
      const r=await api(`/accounts/${integration.id}/kaspi/orders/${encodeURIComponent(kaspiAction.order_id)}/status`,{method:"POST",body});
      ctx.notify(`Kaspi: статус заказа изменён на ${kaspiAction.status}`);
      return r;
    } catch(e){setError(e.message)} finally{setBusy(false)}
  };
  const disconnectIntegration = async () => {
    if(!confirm(`Отключить ${integration.channel}?`)) return;
    setBusy(true);
    try { await api(`/accounts/${integration.id}/credentials`,{method:"DELETE"}); ctx.notify("Интеграция отключена"); setIntegration(null); }
    catch(e){setError(e.message)} finally{setBusy(false)}
  };
  const sync = async (row) => {
    setBusy(true);
    setError("");
    try {
      let r = await api(`/accounts/${row.id}/sync-now?background=true`, { method: "POST" });
      if (r.status === 'running') {
        ctx.notify(`${row.channel}: синхронизация выполняется…`);
        for (let attempt=0;attempt<90;attempt++) {
          await new Promise(resolve=>setTimeout(resolve,2000));
          const status = await api(`/accounts/${row.id}/sync-status`, {timeoutMs:10000});
          if (status.status==='failed') throw new Error(status.error || 'Ошибка синхронизации');
          if (status.status!=='running') {
            ctx.notify(`${row.channel}: всего API-записей ${status.total_records}; всего проведено ${status.erp_projection.total_projected}; ожидает ${status.erp_projection.pending_erp}${status.error ? '; ' + status.error : ''}`);
            return;
          }
        }
        throw new Error('Синхронизация продолжается. Статус сохранён в интеграции; проверьте позже.');
      }
      ctx.notify(`${row.channel}: API ${r.records?.length ?? 0}; новых ${r.staged_inserted ?? 0}; обновлено ${r.staged_updated ?? 0}; проведено в ERP ${r.erp_projection?.projected ?? 0}; ожидает сверки ${r.erp_projection?.pending_erp ?? 0}${r.warnings?.length ? "; неполная выгрузка: " + r.warnings.join("; ") : ""}`);
      ctx.notify("Данные обновлены");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const upload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const cid = ctx.company || ctx.refs.companies?.[0]?.id;
    if (!cid) {
      setError("Сначала добавьте компанию");
      return;
    }
    const f = new FormData();
    f.append("file", file);
    f.append("company_id", cid);
    setBusy(true);
    try {
      await api("/documents/upload", { method: "POST", body: f });
      ctx.notify("Документ загружен");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };
  return (
    <>
      <ErrorBox error={error} />
      {integration && <div className="modal-backdrop" onMouseDown={e=>e.target===e.currentTarget&&setIntegration(null)}>
        <section className="modal" role="dialog" aria-modal="true">
          <div className="modal-heading"><div><h2>{integration.channel} API</h2><p>Безопасное подключение прямо из QOR</p></div><button className="icon-button" onClick={()=>setIntegration(null)}><X size={18}/></button></div>
          <div className="info-banner"><ShieldCheck size={18}/> Ключ сохраняется на сервере в зашифрованном виде и никогда не возвращается в браузер.</div>
          {integration.connection?.saved_on_site && <p><b>Подключение сохранено</b> · {integration.connection.credential_hint}</p>}
          {integration.channel === "Kaspi" && integration.connection?.saved_on_site && <div className="panel"><h3>Управление реальным заказом Kaspi</h3><p className="muted">Операция отправляется прямо в Kaspi. Перед отправкой QOR попросит подтверждение.</p><label>ID заказа Kaspi<input value={kaspiAction.order_id} onChange={e=>setKaspiAction({...kaspiAction,order_id:e.target.value})} placeholder="ID из синхронизации"/></label><label>Номер заказа<input value={kaspiAction.code} onChange={e=>setKaspiAction({...kaspiAction,code:e.target.value})} placeholder="Код заказа"/></label><label>Действие<select value={kaspiAction.status} onChange={e=>setKaspiAction({...kaspiAction,status:e.target.value})}><option value="ACCEPTED_BY_MERCHANT">Принять заказ</option><option value="ASSEMBLE">Скомплектовать / передать</option><option value="ARRIVED">Прибыл (предзаказ)</option><option value="CANCELLED">Отменить</option><option value="COMPLETED">Выдать покупателю</option></select></label>{kaspiAction.status==="ASSEMBLE"&&<label>Количество мест<input type="number" min="1" value={kaspiAction.number_of_space} onChange={e=>setKaspiAction({...kaspiAction,number_of_space:e.target.value})}/></label>}{kaspiAction.status==="CANCELLED"&&<><label>Причина<select value={kaspiAction.cancellation_reason} onChange={e=>setKaspiAction({...kaspiAction,cancellation_reason:e.target.value})}><option value="BUYER_CANCELLATION_BY_MERCHANT">Покупатель отменил</option><option value="BUYER_NOT_REACHABLE">Не удалось связаться</option><option value="MERCHANT_OUT_OF_STOCK">Нет в наличии</option></select></label><label>Комментарий<input value={kaspiAction.cancellation_comment} onChange={e=>setKaspiAction({...kaspiAction,cancellation_comment:e.target.value})}/></label></>}{kaspiAction.status==="COMPLETED"&&<label>Код покупателя<input value={kaspiAction.security_code} onChange={e=>setKaspiAction({...kaspiAction,security_code:e.target.value})} placeholder="Оставьте пустым для отправки кода"/></label>}<button className="primary" onClick={runKaspiAction} disabled={busy}>{busy?"Отправка…":"Выполнить в Kaspi"}</button></div>}
          {integration.channel === "Ozon" ? <><label>Client ID<input value={integrationForm.client_id} onChange={e=>setIntegrationForm({...integrationForm,client_id:e.target.value})} autoComplete="off"/></label><label>API Key<input type="password" value={integrationForm.api_key} onChange={e=>setIntegrationForm({...integrationForm,api_key:e.target.value})} autoComplete="new-password"/></label></> : <label>API Token<input type="password" value={integrationForm.token} onChange={e=>setIntegrationForm({...integrationForm,token:e.target.value})} placeholder={`Вставьте токен ${integration.channel}`} autoComplete="new-password"/></label>}
          {integration.connection?.saved_on_site && integration.channel === "Kaspi" && <div className="panel padded wide marketplace-sync-settings"><h3>Автообновление цены и остатка Kaspi</h3><p className="muted">Kaspi забирает XML прайс-лист примерно раз в час. QOR отдаёт только товары, сопоставленные с этим магазином; цена берётся из товара, количество — из выделенного остатка.</p><label>Код склада из Kaspi → «Склады и магазины»<input value={integrationSettings.kaspi_store_id || ""} onChange={e=>setIntegrationSettings({...integrationSettings,kaspi_store_id:e.target.value})}/></label><label>Merchant ID продавца из кабинета Kaspi<input value={integrationSettings.kaspi_merchant_id || ""} onChange={e=>setIntegrationSettings({...integrationSettings,kaspi_merchant_id:e.target.value})}/></label><label className="check-label"><input type="checkbox" checked={!!integrationSettings.kaspi_full_catalog_confirmed} onChange={e=>setIntegrationSettings({...integrationSettings,kaspi_full_catalog_confirmed:e.target.checked})}/> Проверил: все товары действующего прайс-листа Kaspi сопоставлены в QOR</label><button className="secondary" onClick={saveMarketplaceSettings} disabled={busy}>Сохранить настройки прайс-листа</button><button className="primary" onClick={createKaspiFeedUrl} disabled={busy || !integrationSettings.kaspi_full_catalog_confirmed}>{integrationSettings.kaspi_feed_configured ? "Создать новую ссылку прайс-листа" : "Сгенерировать ссылку для Kaspi"}</button>{kaspiFeedUrl&&<label>Ссылка. Скопируйте её в кабинете Kaspi<input readOnly value={kaspiFeedUrl} onFocus={e=>e.target.select()}/><small>Ссылка даёт доступ к этому прайс-листу. При утечке создайте новую ссылку.</small></label>}</div>}
          {integration.connection?.saved_on_site && integration.channel === "Wildberries" && <div className="panel padded wide marketplace-sync-settings"><h3>Синхронизация цены и остатков WB</h3><p className="muted">Работает для уже сопоставленных карточек и размеров на складе продавца FBS. QOR сохраняет скидку WB при обновлении цены. Настройка автоматической отправки выключена до вашего включения.</p><button className="secondary" onClick={loadWBWarehouses} disabled={busy}>{busy?"Загрузка…":"Загрузить склады продавца"}</button><label>Склад продавца<select value={integrationSettings.wb_warehouse_id || ""} onChange={e=>setIntegrationSettings({...integrationSettings,wb_warehouse_id:e.target.value})}><option value="">Выберите склад WB</option>{wbWarehouses.map(w=><option key={w.id ?? w.ID} value={w.id ?? w.ID}>{w.name || w.address || "Склад"} · #{w.id ?? w.ID}</option>)}</select></label><label className="check-label"><input type="checkbox" checked={!!integrationSettings.auto_sync} onChange={e=>setIntegrationSettings({...integrationSettings,auto_sync:e.target.checked})}/> Автоматически отправлять изменения цены и распределённого остатка после сохранения товара, инвентаризации и продажи</label><button className="primary" onClick={saveMarketplaceSettings} disabled={busy}>Сохранить настройки WB</button></div>}
          <div className="modal-footer">{integration.connection?.saved_on_site&&<button className="danger" onClick={disconnectIntegration} disabled={busy}>Отключить</button>}{integration.connection?.saved_on_site&&<button className="secondary" onClick={testIntegration} disabled={busy}>{busy?"Проверка…":"Проверить подключение"}</button>}<button className="secondary" onClick={()=>setIntegration(null)}>Отмена</button><button className="primary" onClick={saveIntegration} disabled={busy}>{busy?"Сохранение…":"Сохранить подключение"}</button></div>
        </section>
      </div>}
      {entity === "accounts" && (
        <div className="info-banner">
          <PlugLabel />
          Управляйте подключениями Kaspi, Wildberries и Ozon прямо здесь. Добавьте интеграцию, откройте кнопку защиты, сохраните API-данные, проверьте подключение и запустите синхронизацию отдельной кнопкой. Статус, последняя синхронизация и ошибки видны в таблице. Ключи хранятся на сервере в зашифрованном виде.
        </div>
      )}
      {entity === "niches" && (
        <div className="info-banner">
          Оценка строится только по введённым наблюдениям. Укажите источник и
          дату. Без необходимых показателей система покажет «Недостаточно
          данных». Сезонность и отзывы сохраняются в исходных данных.
        </div>
      )}
      {channels.includes(page) && ["Kaspi", "Wildberries", "Ozon"].includes(page) && <MarketplaceInbox channel={page} ctx={ctx} />}
      {page === "Offline" && <div className="info-banner offline-sales-help"><div><b>Продажа в магазине, по телефону или при самовывозе?</b><span>Нажмите «Записать офлайн-продажу», выберите товар, количество, цену и дату. После проведения продажа появится в учёте и уменьшит общий склад.</span></div><button className="primary" onClick={()=>openSale("Offline")}>Записать офлайн-продажу</button></div>}
      <div className="panel">
        {channels.includes(page) && <div className="section-heading"><div><h3>Подтверждённые продажи</h3><p className="muted">Только операции, проведённые финансовым ядром QOR. Заказ сам по себе не превращается в выручку.</p></div></div>}
        <div className={`table-toolbar${entity === "products" ? " product-catalog-toolbar" : ""}`}>
          <div className="search">
            <Search size={17} />
            <input
              placeholder="Поиск по записям…"
              aria-label="Поиск"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="row-actions">
            {entity === "products" && <>
              {page === "marketplace-products" && writable && <button className="secondary" onClick={loadWBProductCatalogs} disabled={busy || ["queued","running"].includes(productCatalogJob?.status)} title="Загрузка карточек WB отдельно от финансовой синхронизации">{["queued","running"].includes(productCatalogJob?.status) ? "Загружаем каталог WB…" : "Загрузить каталог WB"}</button>}
              {page === "marketplace-products" && writable && <button className="secondary" onClick={autoMatchProducts} disabled={busy} title="Находит новые однозначные совпадения по точному артикулу. Сохранённые связи не создаются повторно.">{busy ? "Проверяем артикулы…" : "Найти связи по артикулам"}</button>}
              <select aria-label="Категория товара" value={catalogCategory} onChange={e=>setCatalogCategory(e.target.value)}><option value="">Все категории</option>{[...new Set((state.data?.items || []).map(p=>p.category).filter(Boolean))].sort().map(x=><option key={x}>{x}</option>)}</select>
              <select aria-label="Сортировка каталога" value={catalogSort} onChange={e=>setCatalogSort(e.target.value)}><option value="name">Название</option><option value="price">Цена ↑</option></select>

              {selectedProducts.length > 0 && <button className="secondary" disabled={busy} onClick={bulkPrice}>Цена для выбранных ({selectedProducts.length})</button>}
            </>}
            <a
              className="secondary"
              href={"/api/export/" + entity + "?format=xlsx&start=" + encodeURIComponent(ctx.start || "") + "&end=" + encodeURIComponent(ctx.end || "") + (ctx.company ? "&company_id=" + ctx.company : "")}
            >
              <Download size={16} />
              Excel
            </a>
            {channels.includes(page) && writable && (
              <button
                className="primary"
                onClick={() => openSale(page)}
              >
                <Plus size={16} />
                {page === "Offline" ? "Записать офлайн-продажу" : "Продажа"}
              </button>
            )}
            {page === "sales" && writable && <button className="primary" onClick={()=>openSale("Offline")}><Plus size={16}/>Записать офлайн-продажу</button>}
            {entity === "documents" && writable && (
              <label className="primary file-button">
                <Upload size={16} />
                {busy ? "Загружаем…" : "Загрузить"}
                <input
                  disabled={busy}
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.webp,.csv,.xlsx"
                  onChange={upload}
                />
              </label>
            )}
          </div>
        </div>
        {entity === "products" && <div className="product-link-filters" role="group" aria-label="Фильтр связей с магазинами">
          <span>Связи на этой странице · карточек {catalogLinkCounts.all}</span>
          {[["all","Все"],["linked","Все магазины связаны"],["needs_link","Требуют связи"],["error","Ошибка синхронизации"]].map(([key,label])=><button type="button" key={key} className={catalogLinkFilter===key?"active":""} aria-pressed={catalogLinkFilter===key} onClick={()=>setCatalogLinkFilter(key)}>{label} <b>{catalogLinkCounts[key]}</b></button>)}
        </div>}
        {entity === "products" && productCatalogJob && <div className="product-match-summary" role="status"><b>Каталог WB · {productCatalogJob.status === "running" ? "загружается" : productCatalogJob.status === "queued" ? "в очереди" : productCatalogJob.status}</b><span>{Object.values(productCatalogJob.payload?.accounts || {}).map(row=>`${row.account_name || `магазин #${row.account_id || ""}`}: ${row.status}, ${row.records || 0} карточек`).join(" · ")}</span>{productCatalogJob.error && <small>{productCatalogJob.error}</small>}{["partial","failed"].includes(productCatalogJob.status) && productCatalogJob.attempts < 3 && <button type="button" className="secondary" onClick={retryWBProductCatalogs} disabled={busy}>Повторить загрузку</button>}</div>}
        {entity === "products" && productMatchResult && <div className="product-match-summary" role="status">
          <b>{productMatchResult.catalog_refresh ? "Каталог Wildberries сопоставлен" : "Автосопоставление завершено"}</b>
          <span>{productMatchResult.catalog_refresh ? `${productMatchResult.accounts_scanned} магазинов WB обработано · ${productMatchResult.products_scanned} артикулов каталога · ${productMatchResult.products_linked} товаров-магазинов сопоставлено · ${productMatchResult.links_created} ID-связей добавлено` : `${productMatchResult.products_scanned} товаров проверено · ${productMatchResult.products_linked} связей товар-магазин · ${productMatchResult.links_created} ID-связей добавлено · ${productMatchResult.already_linked} ID уже были связаны`}</span>
          {productMatchResult.accounts_scanned > productMatchResult.catalog_accounts && <small>Не во всех магазинах загружены карточки для сопоставления. Kaspi API сообщает артикулы товаров из заказов; полный каталог Kaspi автоматически через доступные методы не загружается.</small>}
          {(productMatchResult.review || []).length > 0 && <ul>{productMatchResult.review.map((row,index)=><li key={`${row.product_id}:${row.account_id}:${index}`}>{row.sku} · {row.account_name}: {row.reason}{row.marketplace_keys?.length ? ` (${row.marketplace_keys.join(", ")})` : ""}</li>)}</ul>}
        </div>}
        {entity === "documents" && (
          <p className="panel-note">
            Максимум 5 МБ. Компания:{" "}
            {ctx.refs.companies?.find((c) => c.id == ctx.company)?.name ||
              ctx.refs.companies?.[0]?.name ||
              "не выбрана"}
            .
          </p>
        )}
        {state.loading ? (
          <Spinner />
        ) : state.error ? (
          <ErrorBox error={state.error} />
        ) : (
          <>
            {entity === "products" ? <>
              <div className="qor-catalog-desktop"><ProductCatalogTable rows={catalogRows} selected={selectedProducts} onSelect={id=>setSelectedProducts(v=>v.includes(id)?v.filter(x=>x!==id):[...v,id])} onEdit={product=>ctx.open("products",product)} onPrice={quickPrice} onDelete={remove} accounts={ctx.refs.accounts || []}/></div>
              <div className="qor-catalog-mobile qor-item-grid qor-catalog-list">{catalogRows.map((product) => <ProductCatalogCard key={product.id} product={product} accounts={ctx.refs.accounts || []} onSync={id=>syncProductWB(product,id)} selected={selectedProducts.includes(product.id)} onSelect={e=>setSelectedProducts(v=>e.target.checked ? [...new Set([...v,product.id])] : v.filter(id=>id!==product.id))} onEdit={accountId=>ctx.open("products", accountId ? {...product,_marketplaceLinkAccountId:accountId,_openMarketplaceSetup:true} : product)} onDelete={() => remove(product)} onPrice={() => quickPrice(product)}/>)}</div>
            </> : entity === "sales" ? <>
              <div className="qor-sales-desktop"><Table rows={state.data.items} cols={["date","account_id","reference","product_id","quantity","revenue","commission","logistics","status"]} refs={ctx.refs} entity="sales" actions={row=><><a className="icon-button" title="Скачать счёт" href={`/api/sales/${row.id}/invoice`}><FileText size={16}/></a>{writable&&<button className="icon-button" title="Возврат товара" onClick={()=>ctx.open("returns",{sale_id:row.id})}><RotateCcw size={16}/></button>}</>}/></div>
              <div className="qor-sales-mobile qor-sales-grid">{state.data.items.map((sale) => <SaleProductCard key={sale.id} sale={sale} product={ctx.refs.products?.find((p) => p.id === sale.product_id)} account={ctx.refs.accounts?.find((a) => a.id === sale.account_id)} onReturn={() => ctx.open("returns", {sale_id:sale.id})}/>)}</div>
            </> : entity === "accounts" ? <section className="qor-integration-grid" aria-label="Подключённые магазины">
              {state.data.items.filter(row=>["Kaspi","Wildberries","Ozon"].includes(row.channel)).map(row=><MarketplaceIntegrationCard key={row.id} row={row} busy={busy} onConfigure={openIntegration} onSync={sync} onEdit={item=>ctx.open("accounts",item)} onDelete={remove}/>)}</section> : <Table
              rows={state.data.items}
              cols={columns[entity] || ["id", "created_at"]}
              refs={ctx.refs}
              entity={entity}
              actions={(row) => (
                <>
                  {forms[entity] &&
                    writable &&
                    (entity !== "users" || ctx.auth.user.role === "Owner") && (
                      <>
                        <button
                          className="icon-button"
                          title="Редактировать"
                          onClick={() => ctx.open(entity, row)}
                        >
                          <Pencil size={16} />
                        </button>
                        {entity !== "users" && (
                          <button
                            className="icon-button danger"
                            title="Удалить"
                            onClick={() => remove(row)}
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </>
                    )}
                  {entity === "returns" && writable && returnNext(row).map(([status, title]) => (
                    <button key={status} className={status === "defective" || status === "written_off" ? "secondary" : "secondary"} disabled={busy} onClick={() => setReturnStatus(row, status)}>{title}</button>
                  ))}
                  {entity === "sales" && (
                    <>
                      <a
                        className="icon-button"
                        title="Скачать счёт"
                        href={"/api/sales/" + row.id + "/invoice"}
                      >
                        <FileText size={17} />
                      </a>
                      {writable && (
                        <button
                          className="icon-button"
                          title="Возврат товара"
                          onClick={() =>
                            ctx.open("returns", { sale_id: row.id })
                          }
                        >
                          <RotateCcw size={17} />
                        </button>
                      )}
                    </>
                  )}
                  {entity === "accounts" && writable && (<>
                    {["Kaspi","Wildberries","Ozon"].includes(row.channel) && <button className="icon-button" disabled={busy} onClick={()=>openIntegration(row)} title={row.active === false ? "Подключить магазин снова" : "Настроить API"}><ShieldCheck size={16}/></button>}
                    <button className="icon-button" disabled={busy || row.active === false} onClick={() => sync(row)} title={row.active === false ? "Сначала подключите магазин" : "Синхронизировать"}><RefreshCw size={16} /></button>
                  </>)}
                  {entity === "documents" && (
                    <a
                      className="icon-button"
                      title="Скачать"
                      href={"/api/documents/" + row.id + "/download"}
                    >
                      <Download size={17} />
                    </a>
                  )}
                  {entity === "generated_documents" && (
                    <a className="icon-button" title="Скачать PDF" href={"/api/generated-documents/" + row.id + "/pdf"}>
                      <Download size={17} />
                    </a>
                  )}
                  {entity === "niches" && (
                    <span className="muted">
                      {row.analysis?.message || row.method}
                    </span>
                  )}
                </>
              )}
            />}
            <div className="pagination">
              <span>
                {state.data.total ? offset + 1 : 0}–
                {Math.min(offset + 30, state.data.total)} из {state.data.total}
              </span>
              <div>
                <button
                  className="secondary"
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 30))}
                >
                  Назад
                </button>
                <button
                  className="secondary"
                  disabled={offset + 30 >= state.data.total}
                  onClick={() => setOffset(offset + 30)}
                >
                  Далее
                </button>
              </div>
            </div>
          </>
        )}
      </div>
      {[
        "sales",
        "purchases",
        "expenses",
        "cash",
        "movements",
        "batches",
      ].includes(entity) && (
        <p className="method">
          Проведённые записи неизменяемы. Возврат товара и корректировка склада
          создают отдельные операции с сохранением истории.
        </p>
      )}
      {productOperation && <ProductOperationModal operation={productOperation} company={ctx.company} onClose={()=>setProductOperation(null)} onSaved={message=>{setProductOperation(null);ctx.notify(message);}}/>}
    </>
  );
}
function PlugLabel() {
  return <span className="badge gray">CONNECTORS</span>;
}
function ReferencePicker({ field, value, options, company, onChange }) {
  const [search, setSearch] = useState(""),
    [remote, setRemote] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    if (!search) {
      setRemote(null);
      return;
    }
    const timer = setTimeout(
      () =>
        api(
          "/data/" +
            field.ref +
            "?limit=50&search=" +
            encodeURIComponent(search) +
            (company && field.ref !== "companies"
              ? "&company_id=" + company
              : ""),
        )
          .then((r) => {
            if (live) {
              setRemote(r.items);
              setError("");
            }
          })
          .catch((e) => {
            if (live) setError(e.message);
          }),
      250,
    );
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [search, company, field.ref]);
  const list = remote || options;
  const current = options.find((x) => x.id == value);
  const combined =
    current && !list.some((x) => x.id == value) ? [current, ...list] : list;
  return (
    <div className="reference-picker">
      <input
        aria-label={"Поиск: " + field.label}
        placeholder="Поиск в справочнике…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <select
        aria-label={field.label}
        required={field.required}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Выберите…</option>
        {combined.map((x) => (
          <option value={x.id} key={x.id}>
            {x.name || x.reference} · #{x.id}
          </option>
        ))}
      </select>
      {error && <small>{error}</small>}
    </div>
  );
}
function EditModal({ kind, item, ctx, close }) {
  const fields = forms[kind];
  const editing =
    item?.id &&
    [
      "companies",
      "products",
      "accounts",
      "customers",
      "users",
      "niches",
    ].includes(kind);
  const initial = Object.fromEntries(
    fields.map((f) => [
      f.key,
      item?.[f.key] ?? (kind === "products" && f.key === "sku" ? `QOR-${today().replaceAll("-", "")}-${globalThis.crypto.randomUUID().slice(0, 6).toUpperCase()}` : undefined) ??
        (f.type === "checkbox"
          ? true
          : f.type === "date"
            ? today()
            : f.type === "select"
              ? f.options[0]
              : f.type === "multiref"
                ? []
                : f.type === "json"
                  ? f.key === "media" ? "[]" : "{}"
                  : f.type === "niche"
                    ? {}
                    : f.key === "company_id"
                      ? ctx.company || ctx.refs.companies?.[0]?.id || ""
                      : f.key === "quantity"
                        ? 1
                        : f.key === "min_stock"
                          ? 5
                          : ""),
    ]),
  );
  for (const f of fields) {
    if (f.type === "money" && item?.[f.key] != null)
      initial[f.key] = item[f.key] / 100;
    if (f.type === "json" && typeof initial[f.key] === "object")
      initial[f.key] = JSON.stringify(initial[f.key], null, 2);
  }
  const [values, setValues] = useState(initial),
    [productWizardStep, setProductWizardStep] = useState(0),
    [outboundAllocations, setOutboundAllocations] = useState(item?.marketplace_stock_allocations || {}),
    [lines, setLines] = useState([
      { product_id: "", quantity: 1, unit_cost: "", currency: "KZT", fx_rate: "1" },
    ]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [aiFacts, setAiFacts] = useState(""),
    [aiBusy, setAiBusy] = useState(false),
    [aiQuestions, setAiQuestions] = useState([]),
    [accountCredentials, setAccountCredentials] = useState({token:"", client_id:"", api_key:""}),
    [initialQuantity, setInitialQuantity] = useState("0"),
    [initialReceiptDate, setInitialReceiptDate] = useState(today());
  const initialMarketplaceIdRows = item?._marketplaceLinkAccountId
    ? [{account_id:String(item._marketplaceLinkAccountId), id_type:ctx.refs.accounts?.find(a=>String(a.id)===String(item._marketplaceLinkAccountId))?.channel === "Wildberries" ? "product" : "sku", external_id:""}]
    : [{account_id:"", id_type:"sku", external_id:""}];
  const [marketplaceIdRows, setMarketplaceIdRows] = useState(initialMarketplaceIdRows);
  const productWizardSections = [
    { title: "Основное", fields: ["sku", "name", "description", "category", "article", "barcode", "brand", "supplier"] },
    { title: "Фотографии", fields: [] },
    { title: "Цена и себестоимость", fields: ["price", "purchase_cost", "min_price"] },
    { title: "Остаток", fields: ["min_stock", "active"] },
    { title: "Карточки площадок", fields: [] },
  ];
  const productWizard = kind === "products" && !editing;
  const advanceProductWizard = () => {
    const missing = productWizardStep === 0
      ? (!productCompanyId ? "Выберите компанию" : !String(values.name || "").trim() ? "Укажите название товара" : !String(values.sku || "").trim() ? "Укажите SKU" : "")
      : "";
    if (missing) { setError(missing); return; }
    setError("");
    setProductWizardStep((step) => Math.min(step + 1, productWizardSections.length - 1));
  };
  const [productCompanyId, setProductCompanyId] = useState(String(
    ctx.company || (item?.specifications?._qor_company_ids || [])[0] || ctx.refs.companies?.[0]?.id || ""
  ));
  const [submissionRef] = useState(() => globalThis.crypto.randomUUID());
  const submitLock = useRef(false);
  const dirty = fields.some((f) => String(values[f.key] ?? "") !== String(initial[f.key] ?? "")) || (!editing && kind === "products" && (initialQuantity !== "0" || initialReceiptDate !== today())) || JSON.stringify(outboundAllocations) !== JSON.stringify(item?.marketplace_stock_allocations || {}) || JSON.stringify(marketplaceIdRows) !== JSON.stringify(initialMarketplaceIdRows);
  const requestClose = useCallback(() => {
    if (dirty && !globalThis.confirm("Есть несохранённые изменения. Закрыть без сохранения?")) return;
    close();
  }, [dirty, close]);
  const creatingOfflineChannel = kind === "accounts" && !editing && values.channel === "Offline";
  const marketplaceCompanyId = kind === "products" ? productCompanyId : values.company_id;
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    const fn = (e) => {
      if (e.key === "Escape") requestClose();
    };
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  }, [requestClose]);
  const set = (k, v) => setValues((x) => ({ ...x, [k]: v }));
  const removePersistedMarketplaceMapping = async (mapping) => {
    if (!globalThis.confirm("Убрать связь этой карточки с SKU? История продаж и складских движений останется без изменений.")) return;
    setBusy(true);
    try {
      await api(`/products/${item.id}/marketplace-mappings`, {
        method: "DELETE",
        body: {account_id: Number(mapping.account_id), external_key: mapping.external_key},
      });
      ctx.notify("Связь карточки удалена; история сохранена");
      ctx.reload?.();
      close();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const addProductPhotos = async (files) => {
    const chosen = Array.from(files || []).slice(0, 8);
    try {
      const encoded = await Promise.all(chosen.map(file => new Promise((resolve, reject) => {
        if (!file.type.startsWith("image/") || file.size > 8 * 1024 * 1024) { reject(new Error("Выберите изображения до 8 МБ")); return; }
        const reader = new globalThis.FileReader();
        reader.onerror = () => reject(new Error("Не удалось прочитать изображение"));
        reader.onload = () => {
          const image = new globalThis.Image();
          image.onerror = () => reject(new Error("Файл не является корректным изображением"));
          image.onload = () => {
            const scale = Math.min(1, 1200 / Math.max(image.width, image.height));
            const canvas = document.createElement("canvas");
            canvas.width = Math.max(1, Math.round(image.width * scale)); canvas.height = Math.max(1, Math.round(image.height * scale));
            canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL("image/jpeg", 0.82));
          };
          image.src = reader.result;
        };
        reader.readAsDataURL(file);
      })));
      const current = JSON.parse(values.media || "[]");
      set("media", JSON.stringify([...current, ...encoded].slice(0, 8), null, 2));
      setError("");
    } catch (e) { setError(e.message); }
  };
  const generateProductDraft = async () => {
    setAiBusy(true); setError(""); setAiQuestions([]);
    try {
      const draft = await api("/products/ai-draft", {method:"POST", body:{facts:aiFacts}});
      if (draft.name) set("name", draft.name);
      if (draft.description) set("description", draft.description);
      if (draft.specifications && Object.keys(draft.specifications).length) {
        let current = {};
        try { current = JSON.parse(values.specifications || "{}"); } catch { current = {}; }
        set("specifications", JSON.stringify({...current, ...draft.specifications}, null, 2));
      }
      setAiQuestions(draft.questions || []);
    } catch(e) { setError(e.message); }
    finally { setAiBusy(false); }
  };
  const submit = async (e) => {
    e.preventDefault();
    if (productWizard && productWizardStep < productWizardSections.length - 1) { advanceProductWizard(); return; }
    if (submitLock.current) return;
    submitLock.current = true;
    setBusy(true);
    setError("");
    try {
      const payload = {};
      for (const f of fields) {
        const v = values[f.key];
        if (f.type === "money")
          payload[f.key] = Math.round(Number(v || 0) * 100);
        else if (f.type === "number") payload[f.key] = Number(v || 0);
        else if (f.type === "ref") payload[f.key] = v ? Number(v) : null;
        else if (f.type === "date") payload[f.key] = v || null;
        else if (f.type === "json") payload[f.key] = JSON.parse(v || "{}");
        else payload[f.key] = v;
      }
      if (kind === "products") {
        if (!editing) {
          const quantity = Number(initialQuantity);
          if (!Number.isInteger(quantity) || quantity < 0) throw new Error("Количество должно быть целым числом от 0");
          if (quantity > 0 && Number(values.purchase_cost || 0) <= 0) throw new Error("Для начального остатка укажите себестоимость за единицу");
          if (quantity > 0 && !initialReceiptDate) throw new Error("Укажите дату поступления товара");
          payload.initial_quantity = quantity;
          payload.initial_receipt_date = quantity > 0 ? initialReceiptDate : null;
        }
        payload.marketplace_stock_allocations = outboundAllocations;
        const specifications = payload.specifications || {};
        if (productCompanyId) {
          const companyIds = [...new Set([...(specifications._qor_company_ids || []), Number(productCompanyId)])];
          payload.specifications = {...specifications, _qor_company_ids:companyIds};
        }
      }
      if (kind === "products" && editing) payload.version = item.version;
      if (kind === "adjustments") payload.reference = submissionRef;
      if (kind === "purchases")
        payload.lines = lines.map((l) => ({
          product_id: Number(l.product_id),
          quantity: Number(l.quantity),
          unit_cost: Math.round(Number(l.unit_cost) * 100),
          currency: String(l.currency || "KZT").toUpperCase(),
          fx_rate: Math.round(Number(l.fx_rate || 1) * 10000),
        }));
      const posted = [
        "purchases",
        "sales",
        "returns",
        "expenses",
        "cash",
        "adjustments",
      ].includes(kind);
      const saved = await api(
        posted
          ? "/post/" + kind
          : "/data/" + kind + (editing ? "/" + item.id : ""),
        { method: editing ? "PUT" : "POST", body: payload },
      );
      if (kind === "accounts" && !editing && ["Kaspi","Wildberries","Ozon"].includes(payload.channel)) {
        const credentials = payload.channel === "Ozon"
          ? {client_id: accountCredentials.client_id.trim(), api_key: accountCredentials.api_key.trim()}
          : {token: accountCredentials.token.trim()};
        const missing = payload.channel === "Ozon"
          ? (!credentials.client_id || !credentials.api_key)
          : !credentials.token;
        if (missing) throw new Error("Введите API-данные интеграции");
        await api(`/accounts/${saved.id}/credentials`, {method:"PUT", body:credentials});
        await api(`/accounts/${saved.id}/sync-now?background=true`, {method:"POST", timeoutMs:10000});
        ctx.notify(`${payload.channel}: интеграция создана, API сохранён, проверка и синхронизация запущены`);
      } else {
        let productSaveMessage = "Товар сохранён";
        if (kind === "products") {
          const identifiers = marketplaceIdRows.filter(row => row.account_id && row.external_id.trim());
          let mappingResult = {reprocessed_records:0, projected_records:0, pending_records:0};
          for (const row of identifiers) {
            const endpoint = `/products/${saved.id}/marketplace-mappings`;
            const body = {account_id:Number(row.account_id), id_type:row.id_type, external_id:row.external_id.trim()};
            try {
              const result = await api(endpoint, {method:"POST", body});
              mappingResult.reprocessed_records += Number(result.reprocessed_records || 0);
              mappingResult.projected_records += Number(result.projected_records || 0);
              mappingResult.pending_records += Number(result.pending_records || 0);
            } catch (mappingError) {
              if (!String(mappingError.message || "").includes("Подтвердите перенос связи") || !globalThis.confirm("Этот ID уже привязан к другому SKU. Перенести его на новый товар? История продаж и складских движений останется у прежнего SKU; новые синхронизации будут идти через этот товар.")) throw mappingError;
              const result = await api(endpoint, {method:"POST", body:{...body, confirm_reassign:true}});
              mappingResult.reprocessed_records += Number(result.reprocessed_records || 0);
              mappingResult.projected_records += Number(result.projected_records || 0);
              mappingResult.pending_records += Number(result.pending_records || 0);
            }
          }
          if (!editing) {
            try {
              const selectedCompanyId = productCompanyId || ctx.company;
              const matched = await api("/products/marketplace-matching/auto", {method:"POST", body:{product_ids:[saved.id], ...(selectedCompanyId ? {company_id:Number(selectedCompanyId)} : {})}});
              productSaveMessage = matched.products_linked
                ? `Товар сохранён и связан с ${matched.products_linked} магазинами по артикулу`
                : matched.review_count
                  ? "Товар сохранён. Совпадения требуют проверки в разделе товаров"
                  : "Товар сохранён. Автоматических совпадений пока нет; каталог магазина должен быть синхронизирован";
            } catch (matchError) {
              productSaveMessage = `Товар сохранён. Автопоиск карточек не завершился: ${matchError.message}`;
            }
          }
          if (editing && identifiers.length) {
            productSaveMessage = mappingResult.projected_records
              ? `Изменения сохранены. Связано записей продаж: ${mappingResult.projected_records}`
              : mappingResult.pending_records
                ? `Связь сохранена. ${mappingResult.pending_records} записей всё ещё требуют проверки данных/остатков`
                : `Изменения сохранены. Карточек связано: ${identifiers.length}`;
          }
          ctx.reload?.();
        }
        ctx.notify(kind === "products" ? productSaveMessage : editing ? "Изменения сохранены" : "Операция выполнена");
      }
      close();
    } catch (e) {
      setError(e.message);
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  };
  const input = (f) => {
    let options = f.ref ? ctx.refs[f.ref] || [] : [];
    if (
      ["accounts", "customers", "sales", "purchases", "expenses"].includes(
        f.ref,
      ) &&
      values.company_id
    )
      options = options.filter((x) => x.company_id == values.company_id);
    const v = values[f.key];
    if (f.type === "checkbox")
      return (
        <input
          type="checkbox"
          checked={!!v}
          onChange={(e) => set(f.key, e.target.checked)}
        />
      );
    if (f.type === "select")
      return (
        <select value={v} onChange={(e) => set(f.key, e.target.value)}>
          {f.options.map((x) =>
            Array.isArray(x) ? (
              <option key={x[0]} value={x[0]}>{x[1]}</option>
            ) : (
              <option key={x} value={x}>{x}</option>
            ),
          )}
        </select>
      );
    if (f.type === "ref")
      return (
        <ReferencePicker
          field={f}
          value={v}
          options={options}
          company={values.company_id}
          onChange={(value) => set(f.key, value)}
        />
      );
    if (f.type === "multiref")
      return (
        <div className="multi-choices">
          {options.map((x) => (
            <label key={x.id}>
              <input
                type="checkbox"
                checked={v.includes(x.id)}
                onChange={(e) =>
                  set(
                    f.key,
                    e.target.checked
                      ? [...v, x.id]
                      : v.filter((id) => id !== x.id),
                  )
                }
              />
              {x.name}
            </label>
          ))}
        </div>
      );
    if (f.type === "longtext")
      return <textarea rows={5} value={v} onChange={(e) => set(f.key, e.target.value)} />;
    if (f.type === "json")
      return (
        <textarea
          rows={4}
          value={v}
          onChange={(e) => set(f.key, e.target.value)}
        />
      );
    if (f.type === "niche")
      return (
        <div className="niche-fields">
          {[
            ["monthly_demand", "Спрос, ед./мес."],
            ["competitors", "Число конкурентов"],
            ["margin_percent", "Маржа, %"],
            ["advertising_percent", "Реклама, % от выручки"],
            ["seasonality_risk", "Риск сезонности, 0–100"],
            ["logistics_percent", "Логистика, % от выручки"],
            ["return_percent", "Возвраты, %"],
            ["rating", "Рейтинг 0–5 (опционально)"],
            ["price", "Цена, ₸"],
            ["purchase_cost", "Закупочная цена, ₸"],
            ["logistics", "Логистика, ₸"],
            ["seasonality", "Сезонность (наблюдения)"],
            ["reviews", "Отзывы (наблюдения)"],
          ].map(([k, l]) => (
            <label key={k}>
              {l}
              <input
                type={
                  ["seasonality", "reviews"].includes(k) ? "text" : "number"
                }
                step="any"
                min="0"
                value={v[k] ?? ""}
                onChange={(e) =>
                  set(f.key, {
                    ...v,
                    [k]: e.target.value === "" ? null : e.target.value,
                  })
                }
              />
            </label>
          ))}
        </div>
      );
    return (
      <input
        autoComplete={f.type === "password" ? "new-password" : "off"}
        type={f.type === "money" || f.type === "number" ? "number" : f.type}
        step={
          f.type === "money" ? "0.01" : f.type === "number" ? "1" : undefined
        }
        min={
          f.signed
            ? undefined
            : (f.min ?? (["money", "number"].includes(f.type) ? 0 : undefined))
        }
        value={v ?? ""}
        required={f.required}
        onChange={(e) => set(f.key, e.target.value)}
      />
    );
  };
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) requestClose();
      }}
    >
      <form
        className="modal"
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-label="Форма документа"
      >
        <div className="modal-heading">
          <div>
            <span className="eyebrow">
              {creatingOfflineChannel ? "НАСТРОЙКА КАНАЛА" : editing ? "РЕДАКТИРОВАНИЕ" : "НОВАЯ ЗАПИСЬ"}
            </span>
            <h2>
              {creatingOfflineChannel ? "Офлайн-продажи" : flat.find((x) => x[0] === kind)?.[1] ||
                {
                  returns: "Возврат товара",
                  adjustments: "Корректировка склада",
                }[kind]}
            </h2>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={requestClose}
            aria-label="Закрыть"
          >
            <X />
          </button>
        </div>
        {productWizard && <div className="product-wizard-steps" aria-label="Шаги создания товара" role="list">
          {productWizardSections.map((step, index) => <div key={step.title} className={`product-wizard-step${index === productWizardStep ? " active" : index < productWizardStep ? " done" : ""}`} role="listitem" aria-current={index === productWizardStep ? "step" : undefined}><i>{index < productWizardStep ? <CheckCircle2 size={15}/> : index + 1}</i><span>{step.title}</span></div>)}
        </div>}
        {creatingOfflineChannel && <div className="info-banner"><Store size={18}/><span>Это внутренний канал учёта — API подключать не нужно. Укажите компанию и сохраните канал, затем нажмите «Записать офлайн-продажу» ещё раз, чтобы внести товар, количество, цену и дату.</span></div>}
        {kind === "products" && !editing && productWizardStep === 0 && <section className="product-ai-draft wide" aria-label="Создание товара с помощью AI">
          <div><span className="eyebrow">AI PRODUCT STUDIO</span><h3>Заполнить черновик с AI</h3><p className="muted">Вставьте подтверждённые сведения с упаковки или от поставщика. AI предложит название, описание и характеристики; цену, себестоимость и остаток заполните сами.</p></div>
          <label>Сведения о товаре<textarea rows={3} value={aiFacts} onChange={e=>setAiFacts(e.target.value)} placeholder="Например: модель, бренд, цвет, материал и размеры с упаковки"/></label>
          <button type="button" className="secondary" onClick={generateProductDraft} disabled={aiBusy || aiFacts.trim().length < 8}>{aiBusy ? "Готовлю черновик…" : "Составить черновик с AI"}</button>
          {aiQuestions.length > 0 && <div className="product-ai-questions"><b>Проверьте и уточните перед сохранением</b><ul>{aiQuestions.map((q,i)=><li key={i}>{q}</li>)}</ul></div>}
          <small>AI только заполняет поля формы. Товар сохраняется после нажатия «Сохранить».</small>
        </section>}
        {kind === "products" && (!productWizard || productWizardStep === 0) && <label className="wide">Компания, которой принадлежит этот SKU<select required value={productCompanyId} onChange={e=>setProductCompanyId(e.target.value)}><option value="">Выберите компанию</option>{(ctx.refs.companies || []).map(company=><option key={company.id} value={company.id}>{company.name}</option>)}</select><small>Это помогает безопасно сопоставлять товар только с магазинами этой компании.</small></label>}
        {(!productWizard || productWizardStep === 0) && <div className="form-grid">
          {fields.filter((f) => !(kind === "products" && f.type === "json") && (!productWizard || productWizardSections[0].fields.includes(f.key))).map((f) => (
            <label
              key={f.key}
              className={
                ["json", "multiref", "niche"].includes(f.type)
                  ? "wide"
                  : f.type === "checkbox"
                    ? "check-label"
                    : ""
              }
            >
              {f.label}
              {input(f)}
            </label>
          ))}
        </div>}
        {kind === "products" && (!productWizard || productWizardStep === 0) && <p className="muted product-form-help">SKU создан автоматически — при необходимости его можно изменить. Внутренний ID назначается системой. Служебные данные карточки сохраняются автоматически.</p>}
        {kind === "products" && (!productWizard || productWizardStep === 1) && <section className="product-photo-step wide"><div className="product-photo-picker"><label className="secondary">Добавить фото с камеры или устройства<input type="file" accept="image/*" capture="environment" multiple onChange={e=>{addProductPhotos(e.target.files);e.target.value=""}}/></label><small>Фотографии уменьшаются до 1200 px и сохраняются вместе с товаром в PostgreSQL. До 8 фото.</small></div><div className="product-photo-preview-grid">{(()=>{try{return JSON.parse(values.media || "[]").map((src,index)=><figure key={`${index}-${src.slice(0,24)}`}><img src={src} alt={`Фото товара ${index+1}`}/><button type="button" aria-label={`Удалить фото ${index+1}`} onClick={()=>set("media",JSON.stringify(JSON.parse(values.media || "[]").filter((_,i)=>i!==index)))}>×</button></figure>)}catch{return null}})()}</div></section>}
        {kind === "products" && (!productWizard || productWizardStep === 2) && <div className="form-grid product-price-step">{fields.filter(f=>["price","purchase_cost","min_price"].includes(f.key)).map(f=><label key={f.key}>{f.label}{input(f)}</label>)}</div>}
        {kind === "products" && (!productWizard || productWizardStep === 3) && <section className="product-stock-step wide">
          <div className="form-grid">
            {fields.filter(f=>["min_stock","active"].includes(f.key)).map(f=><label key={f.key} className={f.type === "checkbox" ? "check-label" : ""}>{f.label}{input(f)}</label>)}
            {!editing && <label>Количество при поступлении, шт.<input type="number" min="0" max="1000000000" step="1" value={initialQuantity} onChange={e=>setInitialQuantity(e.target.value)}/><small>Начальный приход попадёт в журнал склада.</small></label>}
            {!editing && <label>Дата поступления<input type="date" value={initialReceiptDate} onChange={e=>setInitialReceiptDate(e.target.value)} required={Number(initialQuantity)>0}/></label>}
          </div>
          <p className="muted">{editing ? "Изменения остатка сохраняйте через кнопки + и − на складе: каждое движение останется в истории." : "Если указано количество, начальная партия и карточка товара сохранятся вместе. Для этой партии используется себестоимость выше."}</p>
        </section>}
        {kind === "products" && (!productWizard || productWizardStep === 4) && <details className="product-marketplace-setup" open={Boolean(item?._openMarketplaceSetup || (editing && (item?.marketplace_mappings || []).length) || productWizardStep === 4)}>
          <summary>
            <span><b>Связать Kaspi и Wildberries</b><small>Связь и лимит остатка сохраняются в QOR после сохранения товара. Повторно вводить их после синхронизации не нужно.</small></span>
            <span className="product-marketplace-summary-count">{(item?.marketplace_mappings || []).length ? `Связано: ${(item.marketplace_mappings || []).length}` : "Настроить"}</span>
          </summary>
          <section className="marketplace-sync-settings">
          <h3>Остаток для магазинов</h3>
          <p className="muted">Это только лимит публикации карточек. Физические приходы и остаток ведутся в разделе «Единый склад»; несколько карточек одного аккаунта используют один лимит магазина.</p>
          {(ctx.refs.accounts || []).filter(a=>a.active !== false && ["Kaspi","Wildberries"].includes(a.channel) && (!values.company_id || String(a.company_id) === String(values.company_id))).map(account=>{
            const mappings = (item?.marketplace_mappings || []).filter(m=>m.account_id === account.id);
            const allocation = outboundAllocations[String(account.id)] || {};
            const sizes = [...new Set([
              ...mappings.filter(m=>m.external_key.startsWith("size:")).map(m=>m.external_key.slice(5)),
              ...marketplaceIdRows.filter(row=>String(row.account_id)===String(account.id) && row.id_type==="size" && /^\d+$/.test(row.external_id.trim())).map(row=>row.external_id.trim()),
            ])];
            const updateQuantity = value => setOutboundAllocations(old=>({...old,[String(account.id)]:{...(old[String(account.id)] || {}),quantity:value === "" ? "" : Number(value)}}));
            return <div key={account.id} className="marketplace-allocation">
              <b>{account.channel} · {account.name}</b>
              {account.channel !== "Wildberries" || sizes.length === 0
                ? <label className="marketplace-quantity">Лимит остатка для магазина<input aria-label={`Лимит остатка ${account.channel} ${account.name}`} type="number" min="0" step="1" value={allocation.quantity ?? outboundAllocations[String(account.id)] ?? ""} onChange={e=>updateQuantity(e.target.value)} placeholder="0"/></label>
                : <div className="marketplace-size-allocation"><strong>Распределите остаток по размерам WB</strong><div>{sizes.map(chrt=><label key={chrt}>Размер · chrtId {chrt}<input aria-label={`Остаток WB для размера ${chrt}`} type="number" min="0" step="1" value={allocation.sizes?.[chrt] ?? ""} onChange={e=>setOutboundAllocations(old=>({...old,[String(account.id)]:{...(old[String(account.id)] || {}),quantity:0,sizes:{...(old[String(account.id)]?.sizes || {}),[chrt]:e.target.value === "" ? "" : Number(e.target.value)}}}))} placeholder="0"/></label>)}</div></div>}
              <small className="marketplace-account-status">{mappings.length ? `Карточка связана · ${mappings.map(m=>m.external_key).join(", ")}` : "Карточка не связана. После создания товара привяжите SKU / ID существующей карточки в блоке ниже."}</small>
              {account.channel === "Wildberries" && sizes.length === 0 && <small className="marketplace-account-status">WB отправляет остаток по размерам. После привязки карточки и chrtId добавьте остаток для каждого размера. Пока размер не сопоставлен, в WB ничего не отправляется.</small>}
              {account.channel === "Kaspi" && <small className="marketplace-account-status">Kaspi получает связанные товары через настроенный прайс-лист магазина. Проверьте подключение и SKU в интеграции.</small>}
            </div>;
          })}
          </section>
          <section className="marketplace-sync-settings">
          <h3>Связать существующие карточки</h3>
          <p className="muted">Добавляйте по одной строке на каждый ID. Можно выбрать несколько магазинов Kaspi/Wildberries и добавить 5–6 карточек для каждого магазина: все строки будут связаны с этим одним SKU. Kaspi: используйте seller SKU / артикул из кабинета. Wildberries: добавьте nmID как ID карточки и chrtID каждого размера. При переносе уже связанного ID история продаж останется у прежней записи.</p>
          {(item?.marketplace_mappings || []).map((mapping, index) => <div className="marketplace-allocation" key={`${mapping.account_id}:${mapping.external_key}:${index}`}><b>{(ctx.refs.accounts || []).find(a=>a.id===mapping.account_id)?.channel || mapping.channel} · {(ctx.refs.accounts || []).find(a=>a.id===mapping.account_id)?.name || `магазин ${mapping.account_id}`}</b><small>{mapping.external_key}</small><button type="button" className="secondary" disabled={busy} onClick={()=>removePersistedMarketplaceMapping(mapping)}>Убрать связь</button></div>)}
          {marketplaceIdRows.map((row,index)=><div className="marketplace-allocation" key={index}>
            <label>Магазин<select value={row.account_id} onChange={e=>{const account=(ctx.refs.accounts || []).find(a=>String(a.id)===e.target.value);setMarketplaceIdRows(old=>old.map((x,i)=>i===index?{...x,account_id:e.target.value,id_type:x.external_id.trim()?x.id_type:account?.channel==="Wildberries"?"product":"sku"}:x))}}><option value="">Выберите магазин</option>{(ctx.refs.accounts || []).filter(a=>a.active!==false && ["Kaspi","Wildberries","Ozon"].includes(a.channel) && (!marketplaceCompanyId || String(a.company_id)===String(marketplaceCompanyId))).map(a=><option key={a.id} value={a.id}>{a.channel} · {a.name}</option>)}</select></label>
            <label>Тип ID<select value={row.id_type} onChange={e=>setMarketplaceIdRows(old=>old.map((x,i)=>i===index?{...x,id_type:e.target.value}:x))}><option value="product">ID карточки товара</option><option value="sku">Артикул / seller SKU</option><option value="barcode">Штрихкод</option><option value="size">ID размера WB (chrtId)</option></select></label>
            <label>{row.id_type === "size" ? "ID размера WB (chrtId)" : "ID на площадке"}<input type={row.id_type === "size" ? "number" : "text"} inputMode={row.id_type === "size" ? "numeric" : undefined} min={row.id_type === "size" ? "1" : undefined} value={row.external_id} onChange={e=>setMarketplaceIdRows(old=>old.map((x,i)=>i===index?{...x,external_id:e.target.value}:x))} placeholder={row.id_type === "size" ? "Например, 123456" : "Введите внешний ID"} autoComplete="off"/></label>
            {marketplaceIdRows.length>1&&<button type="button" className="secondary" onClick={()=>setMarketplaceIdRows(old=>old.filter((_,i)=>i!==index))}>Убрать</button>}
          </div>)}
          <button type="button" className="secondary" onClick={()=>setMarketplaceIdRows(old=>[...old,{account_id:"",id_type:"sku",external_id:""}])}>Добавить ID карточки</button>
          </section>
        </details>}
        {kind === "accounts" && !editing && ["Kaspi","Wildberries","Ozon"].includes(values.channel) && (
          <div className="panel padded wide integration-create-box">
            <div className="info-banner"><ShieldCheck size={18}/> API-данные сохраняются на сервере в зашифрованном виде. После создания QOR сразу проверит соединение и запустит синхронизацию.</div>
            {values.channel === "Ozon" ? <>
              <label>Ozon Client ID<input required value={accountCredentials.client_id} onChange={e=>setAccountCredentials({...accountCredentials,client_id:e.target.value})} autoComplete="off" placeholder="Введите Client ID"/></label>
              <label>Ozon API Key<input required type="password" value={accountCredentials.api_key} onChange={e=>setAccountCredentials({...accountCredentials,api_key:e.target.value})} autoComplete="new-password" placeholder="Введите API Key"/></label>
            </> : <label>{values.channel} API Token<input required type="password" value={accountCredentials.token} onChange={e=>setAccountCredentials({...accountCredentials,token:e.target.value})} autoComplete="new-password" placeholder={`Вставьте API Token ${values.channel}`}/></label>}
          </div>
        )}
        {kind === "purchases" && (
          <div className="purchase-lines">
            <h3>Состав закупки</h3>
            {lines.map((l, i) => (
              <div className="purchase-line" key={i}>
                <label>
                  Товар
                  <select
                    required
                    value={l.product_id}
                    onChange={(e) =>
                      setLines(
                        lines.map((x, j) =>
                          j === i ? { ...x, product_id: e.target.value } : x,
                        ),
                      )
                    }
                  >
                    <option value="">Выберите товар</option>
                    {ctx.refs.products?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Количество
                  <input
                    required
                    type="number"
                    min="1"
                    value={l.quantity}
                    onChange={(e) =>
                      setLines(
                        lines.map((x, j) =>
                          j === i ? { ...x, quantity: e.target.value } : x,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  Цена закупки
                  <input
                    required
                    type="number"
                    min="0"
                    step="0.01"
                    value={l.unit_cost}
                    onChange={(e) =>
                      setLines(
                        lines.map((x, j) =>
                          j === i ? { ...x, unit_cost: e.target.value } : x,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  Валюта
                  <select value={l.currency} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, currency: e.target.value } : x))}>
                    <option value="KZT">KZT</option>
                    <option value="CNY">CNY</option>
                    <option value="USD">USD</option>
                  </select>
                </label>
                <label>
                  Курс к ₸
                  <input required type="number" min="0.0001" step="0.0001" value={l.fx_rate} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, fx_rate: e.target.value } : x))} />
                </label>
                <button
                  type="button"
                  className="icon-button danger"
                  disabled={lines.length === 1}
                  onClick={() => setLines(lines.filter((_, j) => j !== i))}
                  title="Убрать строку"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
            <button
              type="button"
              className="secondary"
              onClick={() =>
                setLines([
                  ...lines,
                  { product_id: "", quantity: 1, unit_cost: "", currency: "KZT", fx_rate: "1" },
                ])
              }
            >
              <Plus size={16} />
              Добавить товар
            </button>
            <p className="muted">
              Дополнительные затраты распределяются пропорционально стоимости
              товаров. Цена каждой строки пересчитывается в тенге по указанному курсу.
            </p>
          </div>
        )}
        <ErrorBox error={error} />
        {dirty && <p className="panel-note">Есть несохранённые изменения</p>}
        <div className="modal-footer">
          <button type="button" className="secondary" onClick={close}>
            Отмена
          </button>
          {productWizard && productWizardStep > 0 && <button type="button" className="secondary" disabled={busy} onClick={()=>{setError("");setProductWizardStep(step=>Math.max(0,step-1));}}>Назад</button>}
          {productWizard && productWizardStep < productWizardSections.length - 1
            ? <button type="button" className="primary" disabled={busy} onClick={advanceProductWizard}>Далее <span aria-hidden="true">→</span></button>
            : <button className="primary" disabled={busy}>{busy ? "Сохраняем…" : productWizard ? "Сохранить товар" : editing ? "Сохранить" : creatingOfflineChannel ? "Создать канал" : "Провести"}</button>}
        </div>
      </form>
    </div>
  );
}
const AI_ROLE_TITLES={rick:"AI-руководитель",finance:"Финансовый директор",analyst:"Аналитик маркетплейсов",buyer:"Склад и закупки",marketing:"Маркетинг",content:"Карточки и контент"};
function formatAIInline(line){return String(line).split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part,i)=>part.startsWith("**")&&part.endsWith("**")?<strong key={i}>{part.slice(2,-2)}</strong>:part.startsWith("*")&&part.endsWith("*")?<em key={i}>{part.slice(1,-1)}</em>:part);}
function formatAIMessage(value){const lines=String(value||"").split(/\r?\n/);const out=[];let bullets=[];const flush=()=>{if(bullets.length){out.push(<ul key={"list-"+out.length}>{bullets.map((line,i)=><li key={i}>{formatAIInline(line)}</li>)}</ul>);bullets=[]}};lines.forEach((line,i)=>{const bullet=line.match(/^\s*[-*]\s+(.+)/);if(bullet){bullets.push(bullet[1]);return}flush();if(!line.trim())return;const heading=line.match(/^#{1,3}\s+(.+)/);out.push(heading?<h3 key={i}>{formatAIInline(heading[1])}</h3>:<p key={i}>{formatAIInline(line)}</p>)});flush();return <div className="chat-markdown">{out}</div>}
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
