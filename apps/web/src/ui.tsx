import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ChartLine,
  Clock,
  Database,
  WarningCircle,
  CaretLeft,
  CaretRight,
  MagnifyingGlass,
  X,
  ArrowLeft,
} from "@phosphor-icons/react";
import type { Incident } from "./data";

export const names: Record<string, string> = {
  active: "فعال",
  review: "نیازمند بررسی",
  closed: "بسته‌شده (نمایشی)",
  pending: "در انتظار تأیید",
  approved: "تأیید شده",
  rejected: "رد شده",
  expired: "منقضی شده",
  consumed: "مجوز مصرف شده",
  unknown: "نامشخص",
  healthy: "سالم",
  degraded: "افت عملکرد",
  unhealthy: "ناسالم",
  available: "دریافت شد",
  unavailable: "در دسترس نیست",
  unsupported: "پشتیبانی نشده",
  unverified: "هنوز بررسی نشده",
  not_collected: "جمع‌آوری نشده",
  permission_denied: "مجوز دریافت داده وجود ندارد",
  authentication_failed: "احراز هویت ناموفق",
  not_found: "یافت نشد",
  failed: "دریافت ناموفق",
  exported: "منتشر شده",
  partially_exported: "انتشار جزئی",
  withheld: "متن منتشر نشده",
  empty: "مجموعه واقعاً خالی",
  collection_failed: "جمع‌آوری ناموفق",
  service: "اطلاعات سرویس",
  deployment: "وضعیت دیپلوی",
  metrics: "متریک منابع",
  logs: "لاگ‌ها",
  approval_requested: "ثبت درخواست تأیید",
  approval_granted: "تصمیم تأیید ثبت شد",
  approval_rejected: "تصمیم رد ثبت شد",
  approval_expired: "درخواست منقضی شد",
  authorization_denied: "مجوز صادر نشد",
  authorization_consumed: "مجوز مصرف شد",
  low: "کم‌ریسک",
  medium: "متوسط",
  high: "حساس",
};
export function Label({ value }: { value: string }) {
  return <>{names[value] || value}</>;
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function StateBadge({ value }: { value: string }) {
  return (
    <Badge
      tone={
        [
          "active",
          "rejected",
          "unhealthy",
          "failed",
          "collection_failed",
        ].includes(value)
          ? "danger"
          : ["pending", "review", "expired", "withheld"].includes(value)
            ? "warning"
            : [
                  "approved",
                  "healthy",
                  "available",
                  "exported",
                  "closed",
                ].includes(value)
              ? "success"
              : "neutral"
      }
    >
      <span className="status-dot" />
      <Label value={value} />
    </Badge>
  );
}
export function Panel({
  title,
  icon,
  children,
  action,
  className = "",
}: {
  title?: ReactNode;
  icon?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <header className="panel-heading">
          <h2>
            {icon}
            {title}
          </h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
export function Notice({
  children,
  tone = "warning",
}: {
  children: ReactNode;
  tone?: "warning" | "info" | "danger";
}) {
  return (
    <div className={`notice ${tone}`}>
      <WarningCircle size={20} />
      <div>{children}</div>
    </div>
  );
}
export function Title({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </header>
  );
}
export function Stat({
  title,
  value,
  detail,
  icon,
  tone = "cyan",
}: {
  title: string;
  value: ReactNode;
  detail?: string;
  icon: ReactNode;
  tone?: string;
}) {
  return (
    <div className="stat panel">
      <div>
        <span>{title}</span>
        <strong className={tone}>{value}</strong>
        {detail && <small>{detail}</small>}
      </div>
      <div className={`stat-icon ${tone}`}>{icon}</div>
    </div>
  );
}
export function ChartEmpty({
  title = "روند خطاهای HTTP",
  kind = "HTTP",
}: {
  title?: string;
  kind?: string;
}) {
  return (
    <Panel
      title={title}
      icon={<ChartLine size={20} />}
      action={<Badge>داده‌ای موجود نیست</Badge>}
    >
      <div
        className="empty-chart"
        role="img"
        aria-label={`نمودار ${title}: داده اندازه‌گیری‌شده موجود نیست`}
      >
        <ChartLine size={42} />
        <strong>داده‌ای برای ترسیم نمودار وجود ندارد</strong>
        <span>نمونه‌های زمانی و واحد تأییدشدهٔ {kind} دریافت نشده‌اند.</span>
        <small>مقادیر ناموجود با صفر جایگزین نمی‌شوند.</small>
      </div>
    </Panel>
  );
}
export function LogsAccounting({ record }: { record: Incident }) {
  const log = record.context.log_export;
  return (
    <Panel title="حسابداری انتشار لاگ" icon={<Database size={18} />}>
      <dl className="facts">
        <dt>وضعیت</dt>
        <dd>
          <StateBadge value={log.state} />
        </dd>
        <dt>دریافت شده</dt>
        <dd>{log.received === null ? "نامشخص" : log.received}</dd>
        <dt>منتشر شده</dt>
        <dd>{log.exported}</dd>
        <dt>متن منتشر نشده</dt>
        <dd>{log.withheld}</dd>
      </dl>
      <p className="muted">
        متن خام لاگ در این رابط نمایش داده نمی‌شود. منتشرنشدن به معنی حذف دائمی
        نیست.
      </p>
    </Panel>
  );
}
export function CapabilityList({ record }: { record: Incident }) {
  return (
    <div className="capabilities">
      {record.context.capabilities.map((c) => (
        <article key={c.capability}>
          <div>
            <strong>
              <Label value={c.capability} />
            </strong>
            <StateBadge value={c.availability} />
          </div>
          {c.error_code && (
            <div className="technical">
              <bdi>{c.error_code}</bdi>{" "}
              {c.http_status !== null && <bdi>HTTP {c.http_status}</bdi>}
              <small>
                امکان تلاش مجدد:{" "}
                {c.retryable === null ? "نامشخص" : c.retryable ? "بله" : "خیر"}
              </small>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}
export function Empty({
  title = "داده‌ای موجود نیست",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <Database size={35} />
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Link({
  to,
  children,
  className = "",
}: {
  to: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a
      href={to}
      className={className}
      onClick={(event) => {
        if (
          !event.ctrlKey &&
          !event.metaKey &&
          !event.shiftKey &&
          event.button === 0
        ) {
          event.preventDefault();
          navigate(to);
        }
      }}
    >
      {children}
    </a>
  );
}
export function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
export function useLocation() {
  const [path, setPath] = useState(
    window.location.pathname + window.location.search,
  );
  useEffect(() => {
    const fn = () => setPath(window.location.pathname + window.location.search);
    window.addEventListener("popstate", fn);
    return () => window.removeEventListener("popstate", fn);
  }, []);
  return path;
}
export function DetailsLink({
  to,
  children = "مشاهدهٔ جزئیات",
}: {
  to: string;
  children?: ReactNode;
}) {
  return (
    <Link to={to} className="button primary">
      {children}
      <ArrowLeft size={16} />
    </Link>
  );
}

export type Column<T> = {
  title: string;
  cell: (row: T) => ReactNode;
  sort?: (row: T) => string | number;
};
export function DataGrid<T extends { id: string }>({
  rows,
  columns,
  searchLabel,
  searchValue,
  preview,
  previewSide = "left",
  widePreview = false,
}: {
  rows: T[];
  columns: Column<T>[];
  searchLabel: string;
  searchValue: (row: T) => string;
  preview?: (row: T) => ReactNode;
  previewSide?: "left" | "right";
  widePreview?: boolean;
}) {
  const [query, setQuery] = useState(
    new URLSearchParams(window.location.search).get("q") || "",
  );
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(
    () => new URLSearchParams(window.location.search).get("selected") || "",
  );
  const [sort, setSort] = useState({ index: 0, desc: false });
  const [size, setSize] = useState(5);
  const filtered = rows.filter((row) =>
    searchValue(row)
      .toLocaleLowerCase("fa")
      .includes(query.toLocaleLowerCase("fa")),
  );
  const sorter = columns[sort.index]?.sort;
  const ordered = sorter
    ? [...filtered].sort(
        (a, b) =>
          String(sorter(a)).localeCompare(String(sorter(b)), "fa", {
            numeric: true,
          }) * (sort.desc ? -1 : 1),
      )
    : filtered;
  const current = Math.min(
    page,
    Math.max(0, Math.ceil(ordered.length / size) - 1),
  );
  const visible = ordered.slice(current * size, (current + 1) * size);
  const chosen = visible.find((row) => row.id === selected) || visible[0];
  return (
    <div
      className={
        preview
          ? `master-detail preview-${previewSide} ${widePreview ? "wide-preview" : ""}`
          : "grid-wrap"
      }
    >
      <div className="panel grid-panel">
        <div className="table-tools">
          <label className="search">
            <MagnifyingGlass size={18} />
            <input
              aria-label={searchLabel}
              placeholder={searchLabel}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
                setSelected("");
              }}
            />
          </label>
          <span className="muted">
            {new Intl.NumberFormat("fa").format(filtered.length)} مورد
          </span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {columns.map((col, i) => (
                  <th
                    key={col.title}
                    aria-sort={
                      col.sort && sort.index === i
                        ? sort.desc
                          ? "descending"
                          : "ascending"
                        : undefined
                    }
                  >
                    <button
                      disabled={!col.sort}
                      onClick={() =>
                        setSort({
                          index: i,
                          desc: sort.index === i ? !sort.desc : false,
                        })
                      }
                    >
                      {col.title}
                      {col.sort && sort.index === i
                        ? sort.desc
                          ? " ↓"
                          : " ↑"
                        : ""}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr
                  key={row.id}
                  className={row.id === chosen?.id ? "selected" : ""}
                  onClick={() => setSelected(row.id)}
                >
                  {columns.map((col, i) => (
                    <td key={col.title}>
                      {i === 0 && preview ? (
                        <button
                          className="text-button"
                          onClick={() => setSelected(row.id)}
                          aria-label={`انتخاب ${row.id}`}
                        >
                          {col.cell(row)}
                        </button>
                      ) : (
                        col.cell(row)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {!visible.length && (
            <Empty title="نتیجه‌ای پیدا نشد">
              فیلتر یا عبارت جستجو را تغییر دهید.
            </Empty>
          )}
        </div>
        <div className="pagination">
          <label>
            در هر صفحه{" "}
            <select
              aria-label="تعداد در هر صفحه"
              value={size}
              onChange={(e) => {
                setSize(Number(e.target.value));
                setPage(0);
              }}
            >
              <option>2</option>
              <option>5</option>
              <option>10</option>
            </select>
          </label>
          <div>
            <button
              className="icon-button"
              aria-label="صفحهٔ قبل"
              disabled={current === 0}
              onClick={() => setPage(current - 1)}
            >
              <CaretRight />
            </button>
            <Badge tone="cyan">
              {new Intl.NumberFormat("fa").format(current + 1)}
            </Badge>
            <button
              className="icon-button"
              aria-label="صفحهٔ بعد"
              disabled={(current + 1) * size >= ordered.length}
              onClick={() => setPage(current + 1)}
            >
              <CaretLeft />
            </button>
          </div>
          <small>
            {filtered.length
              ? `${current * size + 1}–${Math.min((current + 1) * size, filtered.length)}`
              : "۰"}{" "}
            از {filtered.length}
          </small>
        </div>
      </div>
      {preview && (
        <aside className="panel selection">
          {chosen ? preview(chosen) : <Empty title="انتخابی وجود ندارد" />}
        </aside>
      )}
    </div>
  );
}
export function Dialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      aria-labelledby="dialog-title"
    >
      <div className="dialog-heading">
        <h2 id="dialog-title">{title}</h2>
        <button
          autoFocus
          className="icon-button"
          aria-label="بستن پنجره"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Timeline({
  events,
  date,
}: {
  events: { kind: string; occurred_at: string }[];
  date: (s: string | null) => string;
}) {
  return (
    <ol className="timeline">
      {events.map((e, i) => (
        <li key={i}>
          <span className="timeline-point" />
          <div>
            <strong>
              <Label value={e.kind} />
            </strong>
            <small>
              <Clock size={12} />
              {date(e.occurred_at)}
            </small>
          </div>
        </li>
      ))}
    </ol>
  );
}
