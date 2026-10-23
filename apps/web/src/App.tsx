import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bell,
  Brain,
  ChartLine,
  Check,
  CheckCircle,
  Clock,
  Cloud,
  Cube,
  Database,
  DownloadSimple,
  FileText,
  Gear,
  Globe,
  House,
  Info,
  List,
  Lock,
  MagnifyingGlass,
  Moon,
  ShieldCheck,
  SpinnerGap,
  Sun,
  UserCircle,
  WarningCircle,
  X,
  ArrowClockwise,
  ArrowLeft,
  Plus,
  RocketLaunch,
} from "@phosphor-icons/react";
import { SetupPage } from "./Setup";
import {
  exportSchema,
  defaults,
  loadState,
  metric,
  mutate,
  readPreferences,
  savePreferences,
  type Approval,
  type Incident,
  type Preferences,
  type UiState,
} from "./data";
import {
  Badge,
  CapabilityList,
  ChartEmpty,
  DataGrid,
  DetailsLink,
  Dialog,
  Empty,
  Label,
  Link,
  LogsAccounting,
  navigate,
  Notice,
  Panel,
  StateBadge,
  Stat,
  Timeline,
  Title,
  useLocation,
  type Column,
} from "./ui";

const navigation = [
  { path: "/", title: "داشبورد", icon: House },
  { path: "/services", title: "سرویس‌ها", icon: Cube },
  { path: "/setup", title: "راه‌اندازی سرویس", icon: RocketLaunch },
  { path: "/incidents", title: "رخدادها", icon: Bell },
  { path: "/analysis", title: "تحلیل هوشمند", icon: Brain },
  { path: "/approvals", title: "تأیید عملیات", icon: ShieldCheck },
  { path: "/reports", title: "گزارش‌ها", icon: ChartLine },
  { path: "/connections/liara", title: "اتصال لیارا", icon: Cloud },
  { path: "/settings", title: "تنظیمات", icon: Gear },
];
const faults: Record<string, string> = {
  INVALID_DATA:
    "داده‌های دریافتی معتبر یا مرتبط نیستند. هیچ تصمیمی بر اساس آن‌ها فعال نمی‌شود.",
  SESSION_UNAVAILABLE:
    "نشست آزمایشی در دسترس نیست. سرور محلی را با گزینهٔ --mock اجرا کنید.",
  BACKEND_UNAVAILABLE: "ارتباط با بک‌اند محلی برقرار نشد.",
  STALE_REVISION:
    "این گزارش تغییر کرده است. اطلاعات تازه را دریافت و دوباره بررسی کنید.",
  MUTATION_FAILED: "درخواست انجام نشد. وضعیت را دوباره دریافت کنید.",
};
type Context = {
  data: UiState;
  date: (stamp: string | null) => string;
  busy: boolean;
  act: (path: string, payload: object) => Promise<boolean>;
  reload: () => Promise<void>;
  notify: (s: string) => void;
};

export function App() {
  const path = useLocation();
  const pathname = path.split("?")[0];
  const [data, setData] = useState<UiState | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [preferences, setPreferences] = useState(readPreferences);
  const [menu, setMenu] = useState(false);
  const [smallScreen, setSmallScreen] = useState(
    () => window.matchMedia("(max-width: 680px)").matches,
  );
  const rail = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const [bell, setBell] = useState(false);
  const [toast, setToast] = useState("");
  const [query, setQuery] = useState("");
  const requestNumber = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const currentPath = useRef(path);
  currentPath.current = path;
  const reload = useCallback(async () => {
    const number = ++requestNumber.current;
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setLoading(true);
    setError("");
    setData(null);
    try {
      const state = await loadState(next.signal);
      if (mounted.current && number === requestNumber.current) setData(state);
    } catch (e) {
      if (
        !next.signal.aborted &&
        mounted.current &&
        number === requestNumber.current
      )
        setError(e instanceof Error ? e.message : "BACKEND_UNAVAILABLE");
    } finally {
      if (mounted.current && number === requestNumber.current)
        setLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void reload();
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, [reload]);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 680px)");
    const update = () => setSmallScreen(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!menu || !smallScreen) return;
    const controls = Array.from(
      rail.current?.querySelectorAll<HTMLElement>("a,button") || [],
    ).filter((element) => element.getClientRects().length);
    controls[0]?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMenu(false);
      }
      if (event.key === "Tab") {
        const first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      menuButton.current?.focus();
    };
  }, [menu, smallScreen]);
  useEffect(() => {
    setMenu(false);
    setBell(false);
    setToast("");
    window.scrollTo({ top: 0 });
  }, [path]);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        preferences.theme === "system"
          ? media.matches
            ? "dark"
            : "light"
          : preferences.theme;
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [preferences.theme]);
  const changePreferences = (p: Preferences) => {
    setPreferences(p);
    const saved = savePreferences(p);
    setToast(
      saved
        ? "ترجیحات این مرورگر ذخیره شد."
        : "ترجیحات اعمال شد؛ ذخیره‌سازی مرورگر در دسترس نیست.",
    );
  };
  const act = async (url: string, payload: object) => {
    const originPath = path;
    setBusy(true);
    try {
      await mutate(url, payload);
      await reload();
      if (currentPath.current === originPath)
        setToast("پاسخ بک‌اند دریافت شد؛ هیچ عملیاتی اجرا نشده است.");
      return true;
    } catch (e) {
      if (currentPath.current === originPath)
        setToast(
          faults[e instanceof Error ? e.message : ""] || "درخواست انجام نشد.",
        );
      return false;
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  const date = (stamp: string | null) =>
    stamp === null
      ? "زمان مشاهده در دسترس نیست"
      : new Intl.DateTimeFormat("fa-IR", {
          dateStyle: "short",
          timeStyle: "short",
          timeZone: preferences.timezone,
        }).format(new Date(stamp));
  const active = navigation.find((n) =>
    n.path === "/" ? pathname === "/" : pathname.startsWith(n.path),
  );
  return (
    <>
      <a className="skip-link" href="#main">
        رفتن به محتوای اصلی
      </a>
      {menu && (
        <button
          className="nav-scrim"
          aria-label="بستن فهرست"
          onClick={() => setMenu(false)}
        />
      )}
      <aside
        ref={rail}
        inert={smallScreen && !menu}
        className={`sidebar ${menu ? "open" : ""}`}
      >
        <Link to="/" className="brand">
          <Cloud size={54} weight="bold" />
          <strong>
            Infra<span>Pilot</span>
          </strong>
          <small>برای سرویس‌های Liara</small>
        </Link>
        <button
          className="mobile-close icon-button"
          aria-label="بستن فهرست"
          onClick={() => setMenu(false)}
        >
          <X />
        </button>
        <nav aria-label="ناوبری اصلی">
          {navigation.map((n) => (
            <Link
              key={n.path}
              to={n.path}
              className={
                active?.path === n.path ? "nav-item active" : "nav-item"
              }
            >
              <n.icon size={21} />
              <span>{n.title}</span>
              {n.path === "/approvals" && data && (
                <span className="nav-count">
                  {
                    data.approvals.filter(
                      (a) => a.state === "pending" && !a.historical,
                    ).length
                  }
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <UserCircle size={34} />
          <div>
            <strong>تیم زیرساخت</strong>
            <small>نشست آزمایشی محلی</small>
          </div>
          <Badge>MOCK</Badge>
        </div>
      </aside>
      <div className="application">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            ref={menuButton}
            aria-expanded={menu}
            aria-label="باز کردن فهرست"
            onClick={() => setMenu(!menu)}
          >
            <List size={24} />
          </button>
          <div className="source-switch">
            <span className="mock-dot" />
            <small>لیارا تأیید نشده</small>
            <button
              className="selected"
              aria-pressed="true"
              onClick={() => navigate("/connections/liara")}
            >
              MOCK
            </button>
            <button disabled title="اتصال و هویت واقعی پیکربندی نشده است">
              REAL
            </button>
          </div>
          <form
            className="global-search"
            onSubmit={(e) => {
              e.preventDefault();
              navigate("/incidents?q=" + encodeURIComponent(query));
            }}
          >
            <MagnifyingGlass size={19} />
            <input
              aria-label="جستجوی سراسری"
              placeholder="جستجو در رخدادها و گزارش‌ها…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>
          <div className="topbar-actions">
            <div className="theme-switch" aria-label="انتخاب تم">
              <button
                aria-label="تم روشن"
                aria-pressed={preferences.theme === "light"}
                onClick={() =>
                  changePreferences({ ...preferences, theme: "light" })
                }
              >
                <Sun size={15} />
                روشن
              </button>
              <button
                aria-label="تم دارک"
                aria-pressed={preferences.theme === "dark"}
                onClick={() =>
                  changePreferences({ ...preferences, theme: "dark" })
                }
              >
                <Moon size={15} />
                دارک
              </button>
            </div>
            <button
              className="icon-button"
              aria-label="نمایش اعلان‌ها"
              aria-expanded={bell}
              onClick={() => setBell(!bell)}
            >
              <Bell size={21} />
            </button>
            <Badge tone="warning">
              <span className="demo-wide">DEMO · دادهٔ ساختگی</span>
              <span className="demo-short">DEMO</span>
            </Badge>
          </div>
          {bell && (
            <aside className="notification-popover panel">
              <h2>اعلان‌های این مرورگر</h2>
              <p>
                {preferences.notifications
                  ? "جمع‌آوری شواهد آزمایشی ناقص است. اتصال واقعی فعال نیست."
                  : "اعلان‌های این مرورگر غیرفعال‌اند."}
              </p>
              <Link to="/settings">تنظیم اعلان‌ها</Link>
            </aside>
          )}
        </header>
        <main id="main" tabIndex={-1}>
          <div className="breadcrumb">
            <Link to="/">مرکز فرمان</Link>
            <span>/</span>
            <span>{active?.title || "صفحه"}</span>
          </div>
          {toast && (
            <div className="toast" role="status">
              {toast}
              <button
                className="icon-button"
                aria-label="بستن پیام"
                onClick={() => setToast("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {loading ? (
            <section className="loading-state" aria-live="polite">
              <SpinnerGap className="spin" size={35} />
              <h1>در حال دریافت گزارش‌های آزمایشی…</h1>
              <p>جمع‌آوری و تشخیص در بک‌اند موجود انجام می‌شوند.</p>
              <div className="skeleton-grid">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} />
                ))}
              </div>
            </section>
          ) : error ? (
            <Panel>
              <Notice tone="danger">
                {faults[error] || faults.BACKEND_UNAVAILABLE}
              </Notice>
              <button className="button primary" onClick={() => void reload()}>
                تلاش دوباره
              </button>
            </Panel>
          ) : data ? (
            <Pages
              key={path}
              path={pathname}
              context={{ data, date, busy, act, reload, notify: setToast }}
              preferences={preferences}
              onPreferences={changePreferences}
            />
          ) : null}
        </main>
        <footer className="app-footer">
          <span>
            <Info size={14} /> محیط نمایشی · اتصال واقعی فعال نیست
          </span>
          <span>MOCK · هیچ عملیات زیرساختی اجرا نشده است</span>
        </footer>
      </div>
    </>
  );
}

function Pages({
  path,
  context: c,
  preferences,
  onPreferences,
}: {
  path: string;
  context: Context;
  preferences: Preferences;
  onPreferences: (p: Preferences) => void;
}) {
  if (path === "/") return <Dashboard c={c} />;
  if (path === "/setup") return <SetupPage c={c} />;
  if (path === "/services") return <Services c={c} />;
  if (path.startsWith("/services/"))
    return path.slice(10) === encodeURIComponent(c.data.service.id) ? (
      <ServiceDetails c={c} />
    ) : (
      <Empty title="سرویس انتخاب‌شده یافت نشد" />
    );
  if (path === "/incidents") return <Incidents c={c} />;
  if (path.startsWith("/incidents/")) {
    const record = c.data.records.find((r) => r.id === path.slice(11));
    return record ? (
      <IncidentDetails c={c} record={record} />
    ) : (
      <Empty title="گزارش انتخاب‌شده یافت نشد" />
    );
  }
  if (path === "/analysis") return <Analysis c={c} />;
  if (path === "/approvals") return <Approvals c={c} />;
  if (path === "/reports") return <Reports c={c} />;
  if (path === "/connections/liara") return <Connection c={c} />;
  if (path === "/settings")
    return <Settings c={c} preferences={preferences} onSave={onPreferences} />;
  return (
    <Empty title="صفحه یافت نشد">
      <Link to="/">بازگشت به داشبورد</Link>
    </Empty>
  );
}

function Dashboard({ c }: { c: Context }) {
  const primary = c.data.records[0];
  const approvals = c.data.approvals.filter(
    (a) => a.state === "pending" && !a.historical,
  );
  const failed = primary.context.capabilities.filter(
    (v) => v.error_code !== null,
  );
  return (
    <>
      <Title
        title="مرکز فرمان زیرساخت"
        description="نمای یکپارچهٔ سرویس، شواهد و تصمیم‌های قابل بررسی"
        action={
          <Link className="button outline" to="/connections/liara">
            <Plus />
            بررسی اتصال
          </Link>
        }
      />
      <div className="stats-grid">
        <Stat
          title="سرویس‌ها"
          value="۱"
          detail="یک سرویس در دادهٔ Mock"
          icon={<Cube size={30} />}
        />
        <Stat
          title="رخداد فعال (نمایشی)"
          value={c.data.records.filter((r) => r.lifecycle === "active").length}
          detail="چرخهٔ رخداد، سناریوی آزمایشی است"
          icon={<WarningCircle size={29} />}
          tone="danger"
        />
        <Stat
          title="درخواست تأیید"
          value={approvals.length}
          detail="تصمیم تأیید، اجرای عملیات نیست"
          icon={<ShieldCheck size={29} />}
          tone="purple"
        />
        <Stat
          title="جمع‌آوری داده"
          value="ناقص"
          detail={`${failed.length} قابلیت با خطای دریافت`}
          icon={<Database size={29} />}
          tone="warning"
        />
      </div>
      <div className="dashboard-top">
        <Panel
          title="تحلیل هوشمند"
          icon={<Brain size={23} />}
          className="analysis-summary"
        >
          <img src="/assets/analysis-orb.png" alt="" />
          <h3>برای تشخیص قطعی، شواهد کافی نداریم</h3>
          <p dir="auto">{primary.report.summary}</p>
          <div className="mini-evidence">
            <span className="status-dot" /> خطاهای ۴۰۳ و ۴۲۹ مربوط به جمع‌آوری
            Provider هستند.
          </div>
          <DetailsLink to={`/incidents/${primary.id}`}>بررسی رخداد</DetailsLink>
        </Panel>
        <ChartEmpty />
      </div>
      <div className="dashboard-bottom">
        <Panel
          title="وضعیت سرویس"
          icon={<Cube size={20} />}
          action={<Link to="/services">مشاهدهٔ سرویس‌ها</Link>}
        >
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>نام سرویس</th>
                  <th>سلامت</th>
                  <th>CPU</th>
                  <th>RAM</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <Link to={"/services/" + c.data.service.id}>
                      <bdi>{c.data.service.id}</bdi>
                    </Link>
                  </td>
                  <td>
                    <StateBadge value={primary.snapshot.status} />
                  </td>
                  <td>{metric(primary.snapshot.cpu_usage_percent, "%")}</td>
                  <td>{metric(primary.snapshot.ram_usage_mib, "MiB")}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <Notice tone="info">
            سلامت برنامه و واحدهای متریک تأیید نشده‌اند.
          </Notice>
        </Panel>
        <Panel
          title="درخواست‌های در انتظار تأیید"
          icon={<ShieldCheck size={20} />}
          action={<Link to="/approvals">مشاهدهٔ همه</Link>}
        >
          {approvals.length ? (
            approvals.slice(0, 2).map((a) => (
              <div className="approval-mini" key={a.id}>
                <h3>نمونهٔ مستقل ری‌استارت سرویس</h3>
                <StateBadge value={a.state} />
                <p>
                  <bdi>{a.id}</bdi> · اجرا نشده
                </p>
                <Link to={"/approvals?selected=" + a.id}>
                  بررسی درخواست <ArrowLeft />
                </Link>
              </div>
            ))
          ) : (
            <Empty title="درخواست معلقی وجود ندارد" />
          )}
        </Panel>
        <div className="stack">
          <Panel title="استفاده از منابع" icon={<ChartLine size={20} />}>
            <div className="resource-unavailable">
              <strong>CPU / RAM</strong>
              <span>دریافت نشده</span>
            </div>
          </Panel>
          <Panel title="فعالیت‌های اخیر" icon={<Clock size={20} />}>
            <ul className="activity-list">
              {c.data.records.slice(0, 3).map((r) => (
                <li key={r.id}>
                  <Link to={"/incidents/" + r.id}>{r.title}</Link>
                  <small>{c.date(r.created_at)}</small>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}

function Services({ c }: { c: Context }) {
  const [health, setHealth] = useState("all");
  const record = c.data.records[0];
  return (
    <>
      <Title
        title="سرویس‌های پروژه"
        description="مدیریت نمای سرویس و پایش وضعیت جمع‌آوری شواهد"
        action={<DetailsLink to="/connections/liara">افزودن اتصال</DetailsLink>}
      />
      <Notice tone="info">
        چهار گزارش آزمایشی، همگی به یک سرویس تعلق دارند. دادهٔ API به معنی سلامت
        برنامه نیست.
      </Notice>
      <div className="filter-bar">
        <ScopeFields c={c} />
        <label>
          سلامت{" "}
          <select
            aria-label="فیلتر سلامت سرویس"
            value={health}
            onChange={(e) => setHealth(e.target.value)}
          >
            <option value="all">همه</option>
            {["unknown", "healthy", "degraded", "unhealthy"].map((s) => (
              <option key={s} value={s}>
                <Label value={s} />
              </option>
            ))}
          </select>
        </label>
      </div>
      <DataGrid
        rows={
          health === "all" || record.snapshot.status === health
            ? [c.data.service]
            : []
        }
        previewSide="right"
        searchLabel="جستجوی نام یا شناسهٔ سرویس"
        searchValue={(s) => s.name + " " + s.id}
        columns={[
          { title: "سرویس", cell: (s) => <bdi>{s.id}</bdi>, sort: (s) => s.id },
          { title: "نوع", cell: () => "سرویس Mock" },
          {
            title: "سلامت",
            cell: () => <StateBadge value={record.snapshot.status} />,
          },
          {
            title: "CPU",
            cell: () => metric(record.snapshot.cpu_usage_percent, "%"),
          },
          {
            title: "RAM",
            cell: () => metric(record.snapshot.ram_usage_mib, "MiB"),
          },
          {
            title: "جمع‌آوری دیپلوی",
            cell: () => (
              <StateBadge value={record.context.capabilities[1].availability} />
            ),
          },
          {
            title: "زمان مشاهده",
            cell: () => c.date(record.snapshot.timestamp),
          },
          { title: "منبع", cell: () => <Badge tone="cyan">MOCK</Badge> },
          {
            title: "جزئیات",
            cell: (s) => <Link to={"/services/" + s.id}>مشاهده</Link>,
          },
        ]}
        preview={(s) => (
          <>
            <Cube size={35} className="cyan" />
            <h2>{s.name}</h2>
            <bdi>{s.id}</bdi>
            <dl className="facts">
              <dt>پروژه</dt>
              <dd>
                <bdi>{s.project}</bdi>
              </dd>
              <dt>سلامت</dt>
              <dd>
                <Label value={record.snapshot.status} />
              </dd>
              <dt>گزارش‌ها</dt>
              <dd>{c.data.records.length}</dd>
              <dt>آخرین مشاهده</dt>
              <dd>{c.date(record.snapshot.timestamp)}</dd>
            </dl>
            <DetailsLink to={"/services/" + s.id}>مشاهدهٔ سرویس</DetailsLink>
          </>
        )}
      />
      <div className="split">
        <Panel title="گزارش‌های جمع‌آوری ناقص">
          <CapabilityList record={c.data.records[0]} />
        </Panel>
        <Panel title="سرویس‌های بدون مشاهدهٔ سلامت">
          <Empty title="سلامت MOCK-service مشخص نیست">
            مقادیر CPU، RAM و زمان پاسخ برنامه دریافت نشده‌اند.
          </Empty>
          <Link to="/connections/liara">بررسی تنظیمات اتصال</Link>
        </Panel>
      </div>
    </>
  );
}

function ScopeFields({
  c,
  severity = false,
}: {
  c: Context;
  severity?: boolean;
}) {
  return (
    <>
      <label>
        سرویس{" "}
        <select disabled aria-label="دامنهٔ سرویس">
          <option>{c.data.service.id}</option>
        </select>
      </label>
      <label>
        منبع{" "}
        <select disabled aria-label="دامنهٔ منبع">
          <option>MOCK</option>
        </select>
      </label>
      {severity && (
        <label>
          شدت{" "}
          <select disabled aria-label="شدت تشخیصی ناموجود">
            <option>ارائه نشده</option>
          </select>
        </label>
      )}
      <small className="muted">
        فقط یک سرویس Mock در دسترس است
        {severity ? "؛ شدت تشخیصی در این خروجی وجود ندارد." : "."}
      </small>
    </>
  );
}
function MetricCards({ record }: { record: Incident }) {
  return (
    <div className="metrics-grid">
      <Stat
        title="سلامت سرویس"
        value={<StateBadge value={record.snapshot.status} />}
        icon={<ShieldCheck size={23} />}
      />
      <Stat
        title="وضعیت دیپلوی"
        value="نامشخص"
        detail="پرچم دیپلوی، اثبات سلامت نیست"
        icon={<Cloud size={23} />}
        tone="warning"
      />
      <Stat
        title="CPU"
        value={metric(record.snapshot.cpu_usage_percent, "%")}
        icon={<ChartLine size={23} />}
      />
      <Stat
        title="RAM"
        value={metric(record.snapshot.ram_usage_mib, "MiB")}
        icon={<Database size={23} />}
      />
      <Stat
        title="لاگ"
        value={<Label value={record.context.log_export.state} />}
        detail="فقط وضعیت انتشار متن"
        icon={<FileText size={23} />}
        tone="neutral"
      />
      <Stat
        title="جمع‌آوری داده"
        value={
          record.context.capabilities.some((v) => v.error_code)
            ? "ناقص"
            : "قابل بررسی"
        }
        icon={<Database size={23} />}
        tone="warning"
      />
    </div>
  );
}
function ServiceDetails({ c }: { c: Context }) {
  const [tab, setTab] = useState("overview");
  const [chart, setChart] = useState("CPU");
  const record = c.data.records[0];
  return (
    <>
      <Title
        title="جزئیات سرویس"
        description="اطلاعات سرویس، قابلیت‌ها و وضعیت جمع‌آوری داده"
      />
      <Panel>
        <div className="service-header">
          <Cube size={37} className="cyan" />
          <div>
            <h2>{c.data.service.name}</h2>
            <bdi>{c.data.service.id}</bdi>
          </div>
          <Badge tone="cyan">MOCK</Badge>
          <StateBadge value={record.snapshot.status} />
          <span className="muted">{c.date(record.snapshot.timestamp)}</span>
        </div>
      </Panel>
      <Tabs
        items={[
          ["overview", "نمای کلی"],
          ["metrics", "متریک‌ها"],
          ["deployments", "دیپلوی و release"],
          ["collection", "داده‌های جمع‌آوری‌شده"],
        ]}
        value={tab}
        onChange={setTab}
      />
      <MetricCards record={record} />
      {(tab === "overview" || tab === "metrics") && (
        <div className="split">
          <Panel
            title="متریک منابع"
            action={
              <select
                aria-label="نوع متریک"
                value={chart}
                onChange={(e) => setChart(e.target.value)}
              >
                <option>CPU</option>
                <option>RAM</option>
              </select>
            }
          >
            <ChartEmpty title={chart} kind={chart} />
          </Panel>
          <Panel title="زمینهٔ جمع‌آوری">
            <dl className="facts">
              <dt>منبع داده</dt>
              <dd>MOCK · ساختگی</dd>
              <dt>جمع‌آوری پایان یافت</dt>
              <dd>{c.date(record.context.collection_finished_at)}</dd>
              <dt>زمان مشاهدهٔ برنامه</dt>
              <dd>ناموجود</dd>
            </dl>
            <Notice>تازگی و منشأ داده تأیید نشده است.</Notice>
            <LogsAccounting record={record} />
          </Panel>
        </div>
      )}
      {tab === "deployments" && (
        <Panel title="دیپلوی و تاریخچهٔ release">
          <Empty title="اطلاعات release جمع‌آوری نشده است">
            آداپتر این قابلیت را دارد؛ این نمای Mock هنوز دادهٔ release ندارد.
          </Empty>
          <Notice tone="info">
            از وضعیت نمایش‌داده‌شده، موفقیت rollout یا سلامت استنتاج نمی‌شود.
          </Notice>
        </Panel>
      )}
      {tab === "collection" && (
        <Panel title="قابلیت‌های Provider">
          <CapabilityList record={record} />
          <LogsAccounting record={record} />
        </Panel>
      )}
      <Panel title="گزارش‌های مرتبط">
        <div className="related-grid">
          {c.data.records.map((r) => (
            <Link className="related" key={r.id} to={"/incidents/" + r.id}>
              <bdi>{r.id}</bdi>
              <strong>{r.title}</strong>
              <StateBadge value={r.lifecycle} />
            </Link>
          ))}
        </div>
      </Panel>
    </>
  );
}
function Tabs({
  items,
  value,
  onChange,
}: {
  items: string[][];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map(([id, label]) => (
        <button
          role="tab"
          key={id}
          aria-selected={id === value}
          onClick={() => onChange(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

const incidentColumns = (date: Context["date"]): Column<Incident>[] => [
  { title: "شناسه", cell: (r) => <bdi>{r.id}</bdi>, sort: (r) => r.id },
  {
    title: "عنوان رخداد",
    cell: (r) => <Link to={"/incidents/" + r.id}>{r.title}</Link>,
    sort: (r) => r.title,
  },
  { title: "سرویس", cell: (r) => <bdi>{r.snapshot.service_id}</bdi> },
  {
    title: "وضعیت نمایشی",
    cell: (r) => <StateBadge value={r.lifecycle} />,
    sort: (r) => r.lifecycle,
  },
  {
    title: "شواهد",
    cell: (r) => r.report.evidence.length,
    sort: (r) => r.report.evidence.length,
  },
  { title: "منبع", cell: () => <Badge tone="cyan">MOCK</Badge> },
  {
    title: "ایجاد گزارش",
    cell: (r) => date(r.created_at),
    sort: (r) => r.created_at,
  },
];
function Incidents({ c }: { c: Context }) {
  const [status, setStatus] = useState("all");
  const [collection, setCollection] = useState("all");
  const rows = c.data.records.filter(
    (r) =>
      (status === "all" || r.lifecycle === status) &&
      (collection === "all" ||
        (collection === "partial") ===
          r.context.capabilities.some((v) => v.error_code !== null)),
  );
  return (
    <>
      <Title
        title="مرکز رخدادها"
        description="پایش شواهد و بررسی گزارش‌های آزمایشی سرویس"
      />
      <div className="incident-stats">
        {(["active", "review", "closed"] as const).map((s) => (
          <button
            key={s}
            className={`panel summary-tile ${s}`}
            onClick={() => setStatus(status === s ? "all" : s)}
          >
            <Label value={s} />
            <strong>
              {c.data.records.filter((r) => r.lifecycle === s).length}
            </strong>
          </button>
        ))}
      </div>
      <div className="filter-bar">
        <ScopeFields c={c} severity />
        <label>
          وضعیت{" "}
          <select
            aria-label="فیلتر وضعیت رخداد"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">همهٔ رخدادها</option>
            <option value="active">فعال</option>
            <option value="review">نیازمند بررسی</option>
            <option value="closed">بسته‌شده (نمایشی)</option>
          </select>
        </label>
        <label>
          جمع‌آوری{" "}
          <select
            aria-label="فیلتر جمع‌آوری"
            value={collection}
            onChange={(e) => setCollection(e.target.value)}
          >
            <option value="all">همهٔ گزارش‌ها</option>
            <option value="partial">دارای خطای دریافت</option>
            <option value="complete">بدون خطای دریافت</option>
          </select>
        </label>
        <Badge tone="cyan">MOCK · چرخهٔ رخداد نمایشی است</Badge>
      </div>
      <DataGrid
        rows={rows}
        columns={incidentColumns(c.date)}
        searchLabel="جستجوی عنوان یا شناسهٔ رخداد"
        searchValue={(r) => r.title + " " + r.id + " " + r.snapshot.service_id}
        preview={(r) => <IncidentPreview c={c} record={r} />}
      />
    </>
  );
}
function IncidentPreview({ c, record: r }: { c: Context; record: Incident }) {
  return (
    <>
      <h2>جزئیات رخداد</h2>
      <bdi className="cyan">{r.id}</bdi>
      <h3>{r.title}</h3>
      <StateBadge value={r.lifecycle} />
      <dl className="facts">
        <dt>سرویس</dt>
        <dd>
          <bdi>{r.snapshot.service_id}</bdi>
        </dd>
        <dt>ایجاد گزارش</dt>
        <dd>{c.date(r.created_at)}</dd>
        <dt>منبع</dt>
        <dd>MOCK</dd>
        <dt>سلامت</dt>
        <dd>نامشخص</dd>
      </dl>
      <p className="report-text" dir="auto">
        {r.report.summary}
      </p>
      <Notice>این وضعیتِ رخداد، نمایشی است و اثبات خرابی سرویس نیست.</Notice>
      <DetailsLink to={"/incidents/" + r.id} />
    </>
  );
}

function IncidentDetails({ c, record: r }: { c: Context; record: Incident }) {
  const [review, setReview] = useState(false);
  const [working, setWorking] = useState(false);
  const related = c.data.approvals.filter(
    (a) => a.record_id === r.id && !a.historical,
  );
  return (
    <>
      <div className="incident-hero panel">
        <div>
          <div className="hero-badges">
            <Badge tone="danger">
              <bdi>{r.id}</bdi>
            </Badge>
            <StateBadge value={r.lifecycle} />
            <Badge tone="warning">محدودیت داده</Badge>
          </div>
          <h1>{r.title}</h1>
          <div className="hero-meta">
            <bdi>{r.snapshot.service_id}</bdi>
            <Badge tone="cyan">MOCK</Badge>
            <small>ایجاد گزارش: {c.date(r.created_at)}</small>
          </div>
          <p>دادهٔ موجود برای تشخیص علت یا تأیید سلامت کافی نیست.</p>
        </div>
        <div className="orb-panel">
          <img src="/assets/analysis-orb.png" alt="" />
          <strong>تحلیل اولیه آماده است</strong>
          <Link to={"/analysis?incident=" + r.id}>بررسی شواهد تشخیص</Link>
        </div>
        <button
          className="button outline hero-refresh"
          disabled={c.busy}
          onClick={() =>
            void c.act(`reports/${r.id}/refresh`, { revision: r.revision })
          }
        >
          <ArrowClockwise />
          تازه‌سازی تحلیل
        </button>
      </div>
      <MetricCards record={r} />
      <div className="incident-columns">
        <Panel title="فرضیه‌های تشخیص" icon={<Brain size={22} />}>
          <Hypotheses record={r} />
          <Notice tone="info">
            اطمینان، امتیاز ابتکاری است؛ احتمال کالیبره‌شده یا اثبات علت نیست.
          </Notice>
        </Panel>
        <Panel
          title="شواهد و زمینهٔ جمع‌آوری"
          icon={<FileText size={21} />}
          action={<Badge tone="cyan">{r.report.evidence.length} شاهد</Badge>}
        >
          <Evidence record={r} />
          <CapabilityList record={r} />
          <Notice>
            جمع‌آوری جزئی انجام شده؛ لاگ و متریک ناموجود، دادهٔ سالم محسوب
            نمی‌شوند.
          </Notice>
        </Panel>
        <Panel
          title="تأیید عملیات حساس"
          icon={<ShieldCheck size={23} />}
          className="approval-panel"
        >
          <Badge tone="purple">نمونهٔ مستقل آزمایشی</Badge>
          <h3>ری‌استارت سرویس</h3>
          <p>
            این نمونه انتخاب اپراتور است؛ از پیشنهاد تشخیص استخراج نشده است.
          </p>
          <Badge tone="danger">اجرا نشده</Badge>
          {related.length ? (
            <>
              <StateBadge value={related[0].state} />
              <Timeline date={c.date} events={related[0].audit} />
              <DetailsLink to={"/approvals?selected=" + related[0].id}>
                بررسی درخواست
              </DetailsLink>
            </>
          ) : (
            <button className="button primary" onClick={() => setReview(true)}>
              بررسی نمونهٔ درخواست تأیید
            </button>
          )}
          <Notice tone="info">تأیید درخواست، صدور مجوز اجرا نیست.</Notice>
        </Panel>
      </div>
      <div className="split">
        <Panel title="اقدام‌های پیشنهادی">
          <div className="action-list">
            {r.report.actions.map((a) => (
              <article key={a.action_id}>
                <div>
                  <h3 dir="auto">{a.title}</h3>
                  <p dir="auto">{a.description}</p>
                  <Badge tone="success">
                    <Label value={a.risk_level} />
                  </Badge>
                  <Badge>اجرا نشده</Badge>
                </div>
                <button
                  className="button outline"
                  onClick={() => setReview(true)}
                >
                  بررسی پیشنهاد
                </button>
              </article>
            ))}
          </div>
          <Notice tone="info">
            پرچم پیشنهاد، تصمیم سیاست یا مجوز اجرا نیست. هیچ عملیات زیرساختی
            فعال نیست.
          </Notice>
        </Panel>
        <Panel title="داده‌های ناموجود و محدودیت‌ها">
          <Limitations record={r} />
        </Panel>
      </div>
      {review && (
        <Dialog
          title="بررسی پیشنهاد و مرز تأیید"
          onClose={() => setReview(false)}
        >
          <p>
            پیشنهاد تشخیص فقط جمع‌آوری اطلاعات بیشتر است. عملیات اجرایی از این
            پیشنهاد ساخته نمی‌شود.
          </p>
          <Notice>
            نمونهٔ جداگانهٔ restart، فقط تصمیم تأیید آزمایشی را در Gate موجود
            ثبت می‌کند. اجرای واقعی غیرفعال است.
          </Notice>
          <label className="check-row">
            <input
              type="checkbox"
              checked={working}
              onChange={(e) => setWorking(e.target.checked)}
            />{" "}
            مستقل‌بودن نمونه و اجرا نشدن عملیات را می‌دانم.
          </label>
          <button
            className="button primary"
            disabled={!working || c.busy}
            onClick={async () => {
              if (
                await c.act(`reports/${r.id}/approval`, {
                  revision: r.revision,
                })
              ) {
                setReview(false);
                navigate("/approvals");
              }
            }}
          >
            ثبت درخواست تأیید آزمایشی
          </button>
        </Dialog>
      )}
    </>
  );
}
function Evidence({ record: r }: { record: Incident }) {
  return (
    <ul className="evidence-list">
      {r.report.evidence.map((e, i) => (
        <li key={e.evidence_id} id={"evidence-" + e.evidence_id} tabIndex={-1}>
          <span className="index-label">
            {new Intl.NumberFormat("fa").format(i + 1).padStart(2, "۰")}
          </span>
          <div>
            <strong dir="auto">{e.description}</strong>
            <small>
              شاهد گزارش‌شده · <bdi>{e.kind}</bdi>
            </small>
          </div>
          <Badge tone="cyan">MOCK</Badge>
        </li>
      ))}
    </ul>
  );
}
function Hypotheses({
  record: r,
  analysis = false,
}: {
  record: Incident;
  analysis?: boolean;
}) {
  return r.report.hypotheses.length ? (
    <ol className="hypotheses">
      {r.report.hypotheses.map((h) => (
        <li key={h.hypothesis_id}>
          <strong dir="auto">{h.explanation}</strong>
          <bdi>
            {new Intl.NumberFormat("fa").format(h.confidence * 100)} / ۱۰۰
          </bdi>
          <progress max={1} value={h.confidence} />
          <div>
            {h.evidence_ids.map((id) =>
              analysis ? (
                <Link
                  to={
                    "/analysis?incident=" +
                    r.id +
                    "&evidence=" +
                    encodeURIComponent(id)
                  }
                  key={id}
                >
                  بررسی شاهد <bdi>{id}</bdi>
                </Link>
              ) : (
                <a href={"#evidence-" + id} key={id}>
                  بررسی شاهد <bdi>{id}</bdi>
                </a>
              ),
            )}
          </div>
        </li>
      ))}
    </ol>
  ) : (
    <Empty title="فرضیهٔ قابل اتکایی تولید نشده است">
      شواهد کافی برای تعیین علت وجود ندارد. داده‌های ناموجود و محدودیت‌ها را
      بررسی کنید.
    </Empty>
  );
}
function Limitations({ record: r }: { record: Incident }) {
  return (
    <>
      <h3>اطلاعات موردنیاز</h3>
      <ul className="text-list">
        {r.report.missing_information.map((t) => (
          <li key={t} dir="auto">
            {t}
          </li>
        ))}
      </ul>
      <details>
        <summary>
          همهٔ محدودیت‌های تشخیص و جمع‌آوری (
          {r.report.limitations.length + r.context.limitations.length})
        </summary>
        <ul className="text-list">
          {[...r.report.limitations, ...r.context.limitations].map((t) => (
            <li key={t} dir="auto">
              {t}
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}

function Analysis({ c }: { c: Context }) {
  const selected = new URLSearchParams(window.location.search).get("incident");
  const r = selected
    ? c.data.records.find((r) => r.id === selected)
    : c.data.records[0];
  const [evidence, setEvidence] = useState(() =>
    Math.max(
      0,
      r?.report.evidence.findIndex(
        (e) =>
          e.evidence_id ===
          new URLSearchParams(window.location.search).get("evidence"),
      ) ?? 0,
    ),
  );
  const [section, setSection] = useState("evidence");
  if (!r) return <Empty title="گزارش تحلیل یافت نشد" />;
  return (
    <>
      <Title
        title="تحلیل شفاف؛ تصمیم قابل بررسی"
        description="نتیجهٔ موتور تشخیص موجود، همراه با شواهد و محدودیت‌های آن"
      />
      <div className="filter-bar">
        <select
          aria-label="انتخاب گزارش تحلیل"
          value={r.id}
          onChange={(e) => navigate("/analysis?incident=" + e.target.value)}
        >
          {c.data.records.map((v) => (
            <option value={v.id} key={v.id}>
              {v.id} · {v.title}
            </option>
          ))}
        </select>
        <Badge tone="cyan">MOCK</Badge>
        <Link to={"/incidents/" + r.id}>بازگشت به رخداد</Link>
      </div>
      <Tabs
        items={[
          ["collection", "جمع‌آوری"],
          ["evidence", "شواهد"],
          ["hypotheses", "فرضیه‌ها"],
          ["recommendations", "پیشنهادها"],
          ["review", "بازبینی انسانی"],
        ]}
        value={section}
        onChange={setSection}
      />
      <div className="analysis-banner panel">
        <img src="/assets/analysis-orb.png" alt="" />
        <div>
          <h2>تحلیل موتور تشخیص کامل شد</h2>
          <p dir="auto">{r.report.summary}</p>
          <Badge>بدون مدل گفت‌وگویی یا LLM</Badge>
        </div>
      </div>
      <div className="split">
        <Panel
          title="بررسی شواهد انتخاب‌شده"
          action={
            <div className="evidence-controls">
              <button
                className="icon-button"
                aria-label="شاهد قبلی"
                disabled={evidence === 0}
                onClick={() => setEvidence(evidence - 1)}
              >
                →
              </button>
              <span>
                {evidence + 1} از {r.report.evidence.length}
              </span>
              <button
                className="icon-button"
                aria-label="شاهد بعدی"
                disabled={evidence >= r.report.evidence.length - 1}
                onClick={() => setEvidence(evidence + 1)}
              >
                ←
              </button>
            </div>
          }
        >
          {r.report.evidence[evidence] ? (
            <p dir="auto" className="evidence-quote">
              {r.report.evidence[evidence].description}
            </p>
          ) : (
            <Empty />
          )}
          <Notice tone="info">
            شرح شاهد از گزارش تشخیص Mock است؛ بدنهٔ خام API یا آرایهٔ لاگ نمایش
            داده نمی‌شود.
          </Notice>
          <div className="question-chips">
            <button onClick={() => setSection("hypotheses")}>
              چه فرضیه‌ای پشتیبانی می‌شود؟
            </button>
            <button onClick={() => setSection("collection")}>
              چه داده‌ای کم است؟
            </button>
            <button onClick={() => setSection("recommendations")}>
              گام بعدی چیست؟
            </button>
          </div>
          <label className="field">
            پرسش آزاد
            <input disabled placeholder="بک‌اند گفت‌وگویی پیکربندی نشده است" />
          </label>
        </Panel>
        <Panel
          title={
            section === "collection"
              ? "زمینهٔ جمع‌آوری"
              : section === "recommendations"
                ? "پیشنهادهای تشخیص"
                : section === "review"
                  ? "بازبینی انسانی"
                  : "فرضیه‌های رتبه‌بندی‌شده"
          }
        >
          {section === "collection" ? (
            <>
              <CapabilityList record={r} />
              <LogsAccounting record={r} />
            </>
          ) : section === "recommendations" ? (
            <>
              {r.report.actions.map((a) => (
                <article className="action-card" key={a.action_id}>
                  <h3 dir="auto">{a.title}</h3>
                  <p dir="auto">{a.description}</p>
                  <Badge>اجرا نشده</Badge>
                </article>
              ))}
              <DetailsLink to={"/incidents/" + r.id}>
                بازبینی پیشنهاد
              </DetailsLink>
            </>
          ) : section === "review" ? (
            <>
              <Notice>
                تصمیم تأیید فقط در صفحهٔ تأیید عملیات و با پاسخ معتبر بک‌اند
                نمایش داده می‌شود.
              </Notice>
              <DetailsLink to="/approvals">مشاهدهٔ درخواست‌ها</DetailsLink>
            </>
          ) : (
            <Hypotheses record={r} analysis />
          )}
        </Panel>
      </div>
      <Panel title="محدودیت‌های تحلیل">
        <Limitations record={r} />
      </Panel>
    </>
  );
}

function SetupRequests({ c }: { c: Context }) {
  const selected = new URLSearchParams(window.location.search).get("setup");
  const plans = c.data.setup_requests;
  if (!plans.length) return null;
  return <Panel title="برنامه‌های راه‌اندازی ثبت‌شده">
    <Notice>برنامه‌های MOCK زیر در بک‌اند ذخیره شده‌اند. ایجاد سرویس در Gate فعلی پشتیبانی نمی‌شود؛ تأیید یا اجرای این برنامه‌ها فعال نیست.</Notice>
    {plans.map((plan) => <article key={plan.id} id={plan.id} className="panel" aria-label={"برنامه " + plan.brief.service_id}>
      <h3>{plan.brief.service_id}</h3>
      <bdi>{plan.id}</bdi>
      {selected === plan.id && <Badge>برنامهٔ ارسال‌شده</Badge>}
      <Badge tone="warning">مسدود · عملیات پشتیبانی نمی‌شود</Badge>
      <dl className="facts">
        <dt>عملیات</dt><dd><bdi>{plan.operation}</bdi></dd>
        <dt>پلتفرم</dt><dd><bdi>{plan.brief.platform}</bdi></dd>
        <dt>پلن آزمایشی</dt><dd><bdi>{plan.brief.plan}</bdi></dd>
        <dt>دامنهٔ درخواستی</dt><dd><bdi>{plan.brief.custom_domain || "تعیین نشده"}</bdi></dd>
        <dt>نام متغیرها</dt><dd><bdi>{plan.brief.environment_keys.join(", ") || "ندارد"}</bdi></dd>
        <dt>زمان ثبت</dt><dd>{c.date(plan.created_at)}</dd>
      </dl>
      <p>مقادیر محیطی دریافت نشده‌اند. مجوز اجرا صادر نشده و هیچ سرویسی ایجاد نشده است.</p>
      {plan.preparation && <>
        <p>گام‌های تولیدشده توسط ماژول Setup:</p>
        <ol>{plan.preparation.step_keys.map((key) => <li key={key}><bdi>{key}</bdi></li>)}</ol>
        <p>وابستگی‌های فراهم‌نشده: <bdi>{plan.preparation.missing_dependencies.join(", ")}</bdi></p>
      </>}
    </article>)}
  </Panel>;
}

function Approvals({ c }: { c: Context }) {
  const [filter, setFilter] = useState("all");
  const [ack, setAck] = useState(false);
  const [confirm, setConfirm] = useState<{
    a: Approval;
    decision: "approve" | "reject";
  } | null>(null);
  const pending = c.data.approvals.filter(
    (a) => a.state === "pending" && !a.historical,
  );
  const rows = c.data.approvals.filter(
    (a) => filter === "all" || a.state === filter,
  );
  return (
    <>
      <Title
        title="مرکز تأیید عملیات"
        description="بازبینی تصمیم‌ها؛ تأیید درخواست از صدور مجوز و اجرا جداست"
      />
      <SetupRequests c={c} />
      <div className="stats-grid">
        {(["pending", "approved", "rejected", "expired"] as const).map((s) => (
          <button
            key={s}
            className="panel summary-tile"
            onClick={() => setFilter(filter === s ? "all" : s)}
          >
            <Label value={s} />
            <strong>
              {
                c.data.approvals.filter((a) => a.state === s && !a.historical)
                  .length
              }
            </strong>
          </button>
        ))}
      </div>
      <Notice>
        درخواست‌های جدول ری‌استارت، نمونهٔ مستقل restart در محیط MOCK هستند؛
        پیشنهاد تشخیص، دستور restart نیست. شمارنده‌ها فقط درخواست‌های جاری را
        نشان می‌دهند؛ جدول سوابق تاریخی را نیز نگه می‌دارد.
      </Notice>
      <div className="filter-bar">
        <label>
          وضعیت درخواست{" "}
          <select
            aria-label="فیلتر تأییدها"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">همه</option>
            {["pending", "approved", "rejected", "expired", "consumed"].map(
              (v) => (
                <option key={v} value={v}>
                  {
                    {
                      pending: "در انتظار",
                      approved: "تأیید شده",
                      rejected: "رد شده",
                      expired: "منقضی شده",
                      consumed: "مصرف شده",
                    }[v as "pending"]
                  }
                </option>
              ),
            )}
          </select>
        </label>
        <Badge>{pending.length} درخواست جاریِ معلق</Badge>
      </div>
      <DataGrid
        rows={rows}
        searchLabel="جستجوی شناسهٔ درخواست"
        previewSide="right"
        widePreview
        searchValue={(a) => a.id + " " + a.record_id}
        columns={[
          {
            title: "درخواست",
            cell: (a) => <bdi>{a.id}</bdi>,
            sort: (a) => a.id,
          },
          {
            title: "رخداد",
            cell: (a) => (
              <Link to={"/incidents/" + a.record_id}>
                <bdi>{a.record_id}</bdi>
              </Link>
            ),
          },
          {
            title: "وضعیت",
            cell: (a) => <StateBadge value={a.state} />,
            sort: (a) => a.state,
          },
          {
            title: "ایجاد",
            cell: (a) => c.date(a.created_at),
            sort: (a) => a.created_at,
          },
        ]}
        preview={(a) => (
          <>
            <h2>نمونهٔ ری‌استارت سرویس</h2>
            <bdi>{a.id}</bdi>
            <div className="hero-badges">
              <StateBadge value={a.state} />
              <Badge tone="danger">اجرا نشده</Badge>
              {a.historical && <Badge>تاریخی · فاقد زمینهٔ جاری</Badge>}
            </div>
            <dl className="facts">
              <dt>سرویس</dt>
              <dd>
                <bdi>{c.data.service.id}</bdi>
              </dd>
              <dt>عملیات</dt>
              <dd>
                <bdi>restart_service</bdi>
              </dd>
              <dt>اعتبار تا</dt>
              <dd>{c.date(a.expires_at)}</dd>
              <dt>مجوز اجرا</dt>
              <dd>صادر نشده</dd>
              <dt>مهلت توقف</dt>
              <dd>
                <bdi>{a.grace_period_seconds} s</bdi>
              </dd>
            </dl>
            <Notice>
              ری‌استارت می‌تواند سرویس را موقتاً قطع کند و عملیات حساس است. هیچ
              executor فعال نیست. این تصمیم فقط در Gate و Audit آزمایشی ثبت
              می‌شود.
            </Notice>
            <Timeline events={a.audit} date={c.date} />
            <div className="button-row">
              <button
                className="button primary"
                disabled={
                  !a.can_decide ||
                  c.busy ||
                  Date.parse(a.expires_at) <= Date.now()
                }
                onClick={() => {
                  setAck(false);
                  setConfirm({ a, decision: "approve" });
                }}
              >
                تأیید درخواست
              </button>
              <button
                className="button danger-button"
                disabled={
                  !a.can_decide ||
                  c.busy ||
                  Date.parse(a.expires_at) <= Date.now()
                }
                onClick={() => {
                  setAck(false);
                  setConfirm({ a, decision: "reject" });
                }}
              >
                رد درخواست
              </button>
            </div>
            {(!a.can_decide || Date.parse(a.expires_at) <= Date.now()) && (
              <p className="muted">
                تصمیم جدید برای این درخواست در دسترس نیست؛ تأیید قبلی مجوز اجرا
                نیست.
              </p>
            )}
          </>
        )}
      />
      {confirm && (
        <Dialog
          title={
            confirm.decision === "approve"
              ? "تأیید درخواست آزمایشی"
              : "رد درخواست آزمایشی"
          }
          onClose={() => setConfirm(null)}
        >
          <p>
            سرویس <bdi>{c.data.service.id}</bdi> · رخداد{" "}
            <bdi>{confirm.a.record_id}</bdi>
          </p>
          <Notice>
            تصمیم در بک‌اند و با هویت بازبین مستقل آزمایشی ثبت می‌شود. هیچ
            عملیات واقعی انجام نمی‌شود.
          </Notice>
          <label className="check-row">
            <input
              type="checkbox"
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
            />{" "}
            دامنهٔ درخواست و مستقل‌بودن نمونه را بررسی کردم.
          </label>
          <button
            className="button primary"
            disabled={!ack || c.busy}
            onClick={async () => {
              if (
                await c.act(`approvals/${confirm.a.id}/decision`, {
                  revision: confirm.a.revision,
                  decision: confirm.decision,
                })
              )
                setConfirm(null);
            }}
          >
            ثبت تصمیم در بک‌اند
          </button>
        </Dialog>
      )}
    </>
  );
}

function Reports({ c }: { c: Context }) {
  const [tab, setTab] = useState("reports");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [selected, setSelected] = useState(c.data.records[0].id);
  const rows = c.data.records.filter(
    (r) =>
      (!from || r.created_at.slice(0, 10) >= from) &&
      (!to || r.created_at.slice(0, 10) <= to),
  );
  const r = c.data.records.find((r) => r.id === selected) || c.data.records[0];
  const events = c.data.approvals
    .flatMap((a) =>
      a.audit.map((e, i) => ({
        id: a.id + "-" + i,
        ...e,
        approval_id: a.id,
        record_id: a.record_id,
      })),
    )
    .filter(
      (e) =>
        (!from || e.occurred_at.slice(0, 10) >= from) &&
        (!to || e.occurred_at.slice(0, 10) <= to),
    );
  const download = async () => {
    try {
      const response = await fetch(`/api/ui/reports/${r.id}/export`, {
        credentials: "same-origin",
      });
      if (!response.ok) throw Error();
      const value = exportSchema.parse(await response.json());
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(value, null, 2)], {
          type: "application/json",
        }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `MOCK-${r.id}-summary.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      c.notify("خلاصهٔ ساختاریافتهٔ MOCK دریافت شد؛ شامل متن خام لاگ نیست.");
    } catch {
      c.notify("دریافت گزارش انجام نشد.");
    }
  };
  return (
    <>
      <Title
        title="گزارش‌ها و ردپای تصمیم"
        description="گزارش‌های تشخیص و سوابق Audit؛ سابقه، مجوز یا شواهد تازه نیست"
      />
      <Tabs
        items={[
          ["reports", "گزارش تشخیص"],
          ["audit", "رویدادهای ممیزی"],
          ["exports", "خروجی‌ها"],
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab !== "exports" && (
        <div className="filter-bar">
          <label>
            از تاریخ (میلادی، UTC)
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label>
            تا تاریخ (میلادی، UTC)
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
          <button
            className="button outline"
            onClick={() => {
              setFrom("");
              setTo("");
            }}
          >
            پاک کردن بازه
          </button>
          <Badge tone="cyan">MOCK</Badge>
        </div>
      )}
      {tab === "audit" ? (
        <DataGrid
          rows={events}
          searchLabel="جستجو در رخدادهای ممیزی"
          searchValue={(e) => e.kind + " " + e.approval_id + " " + e.record_id}
          columns={[
            {
              title: "رویداد",
              cell: (e) => <Label value={e.kind} />,
              sort: (e) => e.kind,
            },
            { title: "درخواست", cell: (e) => <bdi>{e.approval_id}</bdi> },
            { title: "رخداد مرتبط", cell: (e) => <bdi>{e.record_id}</bdi> },
            {
              title: "زمان",
              cell: (e) => c.date(e.occurred_at),
              sort: (e) => e.occurred_at,
            },
            { title: "منبع", cell: () => "MOCK" },
          ]}
        />
      ) : tab === "exports" ? (
        <Panel title="خروجی پاک‌سازی‌شده">
          <label className="field">
            گزارش
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              {c.data.records.map((v) => (
                <option value={v.id} key={v.id}>
                  {v.id} · {v.title}
                </option>
              ))}
            </select>
          </label>
          <Notice tone="info">
            فقط تعداد شواهد، وضعیت قابلیت‌ها و پرچم‌های اجرا صادر می‌شوند. فایل
            پایگاه داده، متن خام و اطلاعات نشست صادر نمی‌شوند.
          </Notice>
          <button className="button primary" onClick={() => void download()}>
            <DownloadSimple />
            دریافت خلاصهٔ MOCK
          </button>
        </Panel>
      ) : (
        <>
          <div className="stats-grid">
            <Stat
              title="گزارش‌های تشخیص"
              value={rows.length}
              icon={<FileText size={28} />}
            />
            <Stat
              title="درخواست‌های بازبینی"
              value={c.data.approvals.length}
              icon={<ShieldCheck size={28} />}
              tone="warning"
            />
            <Stat
              title="عملیات اجراشده"
              value="۰"
              icon={<Lock size={28} />}
              tone="neutral"
            />
            <Stat title="منبع" value="MOCK" icon={<Database size={28} />} />
          </div>
          <DataGrid
            rows={rows}
            columns={incidentColumns(c.date)}
            searchLabel="جستجو در گزارش‌ها"
            previewSide="right"
            searchValue={(v) => v.id + " " + v.title}
            preview={(report) => (
              <>
                <h2>خلاصهٔ گزارش منتخب</h2>
                <bdi className="cyan">{report.id}</bdi>
                <p>{report.title}</p>
                <dl className="facts">
                  <dt>شواهد</dt>
                  <dd>{report.report.evidence.length}</dd>
                  <dt>فرضیه</dt>
                  <dd>{report.report.hypotheses.length}</dd>
                  <dt>محدودیت‌ها</dt>
                  <dd>{report.report.limitations.length}</dd>
                  <dt>منبع</dt>
                  <dd>MOCK</dd>
                </dl>
                <Notice tone="info">
                  خلاصه در SQLite ذخیره شده است. گزارش کامل فعلی از اشیای معتبر
                  همین نشست می‌آید؛ از تاریخچه بازسازی نشده است.
                </Notice>
                <DetailsLink to={"/incidents/" + report.id}>
                  گزارش جاری نشست
                </DetailsLink>
              </>
            )}
          />
        </>
      )}
    </>
  );
}

function Connection({ c }: { c: Context }) {
  const [step, setStep] = useState(1);
  return (
    <>
      <Title
        title="اتصال امن به Liara"
        description="وضعیت واقعی اتصال و داده‌های در دسترس، بدون دریافت توکن در مرورگر"
      />
      <div className="steps">
        <span className={step === 1 ? "active" : ""}>۱ · انتخاب منبع</span>
        <span className={step === 2 ? "active" : ""}>۲ · بررسی دسترسی</span>
        <span className={step === 3 ? "active" : ""}>۳ · انتخاب سرویس</span>
      </div>
      <div className="connection-layout">
        <Panel
          title={
            step === 1
              ? "انتخاب منبع داده"
              : step === 2
                ? "بررسی دسترسی به داده"
                : "سرویس آزمایشی موجود"
          }
        >
          <div className="source-cards">
            <button className="source-card selected" onClick={() => setStep(1)}>
              <Database size={30} />
              <strong>دادهٔ نمایشی MOCK</strong>
              <small>منطق واقعی ماژول‌ها، ورودی ساختگی</small>
              <CheckCircle size={23} />
            </button>
            <div className="source-card unavailable">
              <Cloud size={30} />
              <strong>اتصال واقعی REAL</strong>
              <Badge tone="danger">پیکربندی نشده</Badge>
              <small>هویت و دسترسی واقعی تأیید نشده است</small>
            </div>
          </div>
          {step === 1 ? (
            <>
              <label className="field">
                نام اتصال
                <input value="اتصال آزمایشی محلی" readOnly />
              </label>
              <label className="field">
                شناسهٔ پروژه
                <input value={c.data.service.project} readOnly dir="ltr" />
              </label>
              <label className="field">
                کلید دسترسی
                <input
                  disabled
                  type="password"
                  placeholder="توکن در مرورگر دریافت یا ذخیره نمی‌شود"
                />
              </label>
              <Notice tone="info">
                توکن فقط در محیط امن سرور تنظیم می‌شود. راهنمای{" "}
                <bdi>integration/LIVE_VERIFICATION.md</bdi> را در مخزن ببینید.
              </Notice>
              <div className="button-row">
                <button className="button primary" onClick={() => setStep(2)}>
                  ادامه با دادهٔ نمایشی <ArrowLeft />
                </button>
                <button
                  className="button outline"
                  onClick={() => void c.reload()}
                >
                  بررسی وضعیت فعلی
                </button>
              </div>
            </>
          ) : step === 2 ? (
            <>
              <CapabilityList record={c.data.records[0]} />
              <Notice>
                این نتایج، سناریوی Mock هستند. خطاهای ۴۰۳ و ۴۲۹ به معنی عدم
                پشتیبانی API نیستند.
              </Notice>
              <button className="button primary" onClick={() => setStep(3)}>
                انتخاب سرویس آزمایشی
              </button>
            </>
          ) : (
            <>
              <h3>{c.data.service.name}</h3>
              <bdi>{c.data.service.id}</bdi>
              <Notice tone="info">
                انتخاب این سرویس اتصال زنده ایجاد نمی‌کند.
              </Notice>
              <DetailsLink to={"/services/" + c.data.service.id}>
                مشاهدهٔ سرویس
              </DetailsLink>
            </>
          )}
        </Panel>
        <div className="stack">
          <Panel title="وضعیت اتصال">
            <Badge>بررسی نشده</Badge>
            <h3>اتصال واقعی تأیید نشده است</h3>
            <p>فهرست حساب، مجوزها و سرویس واقعی در این رابط بررسی نشده‌اند.</p>
            <dl className="facts">
              <dt>سرویس‌های واقعی</dt>
              <dd>بررسی نشده</dd>
              <dt>متریک واقعی</dt>
              <dd>بررسی نشده</dd>
              <dt>لاگ واقعی</dt>
              <dd>جمع‌آوری نشده</dd>
            </dl>
            <Badge tone="cyan">دادهٔ این نشست از بک‌اند MOCK دریافت شد</Badge>
          </Panel>
          <Panel>
            <Empty title="منبع سرویس واقعی دریافت نشده">
              برای بررسی زنده از فرمان خواندنیِ مستندشده و پیکربندی امن سرور
              استفاده کنید.
            </Empty>
          </Panel>
        </div>
      </div>
    </>
  );
}

function Settings({
  preferences,
  onSave,
}: {
  c: Context;
  preferences: Preferences;
  onSave: (p: Preferences) => void;
}) {
  const [draft, setDraft] = useState(preferences);
  const [tab, setTab] = useState("appearance");
  return (
    <>
      <Title
        title="تنظیمات فضای کاری"
        description="ترجیحات مرورگر و وضعیت سیاست‌های امنیتی؛ تنظیمات مرورگر مجوز ایجاد نمی‌کنند"
      />
      <Tabs
        items={[
          ["appearance", "ظاهر"],
          ["connections", "اتصال‌ها"],
          ["permissions", "دسترسی‌ها"],
          ["notifications", "اعلان‌ها"],
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "connections" ? (
        <Panel title="اتصال به لیارا">
          <Notice>
            اتصال واقعی تأیید نشده است. هیچ کلیدی در مرورگر ذخیره نشده است.
          </Notice>
          <DetailsLink to="/connections/liara">تنظیمات اتصال</DetailsLink>
        </Panel>
      ) : tab === "permissions" ? (
        <Panel title="سیاست تأیید عملیات حساس">
          <dl className="facts">
            <dt>مدت اعتبار پیش‌فرض</dt>
            <dd>۵ دقیقه؛ حداکثر ۱۵ دقیقه در Gate</dd>
            <dt>بازبین</dt>
            <dd>مستقل از درخواست‌کننده</dd>
            <dt>هویت واقعی</dt>
            <dd>پیکربندی نشده</dd>
            <dt>اجرای عملیات</dt>
            <dd>غیرفعال</dd>
          </dl>
          <Notice tone="info">
            نقش، مجوز و انقضای درخواست از این صفحه تغییر نمی‌کنند.
          </Notice>
        </Panel>
      ) : (
        <div className="settings-grid">
          <Panel title="ظاهر رابط کاربری" icon={<Sun size={20} />}>
            <p className="muted">حالت نمایش برنامه را انتخاب کنید.</p>
            <div className="theme-cards">
              {(["dark", "light", "system"] as const).map((theme) => (
                <label
                  key={theme}
                  className={`theme-card ${draft.theme === theme ? "selected" : ""}`}
                >
                  <span className={"theme-preview " + theme}>
                    {theme === "dark" ? (
                      <Moon size={32} />
                    ) : theme === "light" ? (
                      <Sun size={32} />
                    ) : (
                      <Globe size={32} />
                    )}
                  </span>
                  <span>
                    <input
                      type="radio"
                      name="theme"
                      value={theme}
                      checked={draft.theme === theme}
                      onChange={() => setDraft({ ...draft, theme })}
                    />
                    {theme === "dark"
                      ? "دارک"
                      : theme === "light"
                        ? "روشن"
                        : "پیروی از سیستم"}
                  </span>
                </label>
              ))}
            </div>
            <p className="muted">
              فقط ترجیحات بی‌خطر در همین مرورگر ذخیره می‌شوند.
            </p>
          </Panel>
          <Panel title="زبان و منطقهٔ زمانی" icon={<Globe size={20} />}>
            <label className="field">
              زبان برنامه
              <select disabled value="fa" onChange={() => {}}>
                <option value="fa">فارسی</option>
              </select>
            </label>
            <label className="field">
              منطقهٔ زمانی
              <select
                value={draft.timezone}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    timezone: e.target.value as Preferences["timezone"],
                  })
                }
              >
                <option value="Asia/Tehran">تهران · Asia/Tehran</option>
                <option value="UTC">UTC</option>
              </select>
            </label>
            <p className="muted">
              زمانِ مشاهدهٔ ناموجود با زمان فعلی پر نمی‌شود.
            </p>
          </Panel>
          <Panel title="اعلان‌های این مرورگر" icon={<Bell size={20} />}>
            <label className="check-row">
              <input
                type="checkbox"
                checked={draft.notifications}
                onChange={(e) =>
                  setDraft({ ...draft, notifications: e.target.checked })
                }
              />{" "}
              نمایش یادآوری رخدادها و محدودیت‌های داده
            </label>
            <Notice tone="info">
              اعلان push، ایمیل و ارسال بیرون از برنامه فعال نیست.
            </Notice>
          </Panel>
          <Panel title="منبع دادهٔ پیش‌فرض" icon={<Database size={20} />}>
            <Badge tone="cyan">MOCK · دادهٔ نمایشی</Badge>
            <p>انتخاب REAL تا آماده‌شدن مسیر معتبر بک‌اند در دسترس نیست.</p>
            <Notice>برچسب DEMO برای دادهٔ Mock همیشه نمایش داده می‌شود.</Notice>
          </Panel>
        </div>
      )}
      <div className="settings-actions">
        <button className="button primary" onClick={() => onSave(draft)}>
          <Check />
          ذخیرهٔ ترجیحات مرورگر
        </button>
        <button
          className="button outline"
          onClick={() => {
            setDraft({ ...defaults });
            onSave({ ...defaults });
          }}
        >
          بازگردانی پیش‌فرض‌ها
        </button>
        <span className="muted">
          هیچ سیاست یا تنظیمی در لیارا تغییر نمی‌کند.
        </span>
      </div>
    </>
  );
}
