import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle,
  Cube,
  Eye,
  EyeSlash,
  Globe,
  Lock,
  Plus,
  ShieldCheck,
  Trash,
  WarningCircle,
  Cpu,
} from "@phosphor-icons/react";
import { Badge, Notice, Panel, Title, navigate } from "./ui";
import { submitSetup, validSetupDomain, type SetupBrief, type UiState } from "./data";

export interface SetupContext {
  data: UiState;
  date: (stamp: string | null) => string;
  busy: boolean;
  act: (path: string, payload: object) => Promise<boolean>;
  reload: () => Promise<void>;
  notify: (s: string) => void;
}

interface EnvVar {
  id: string;
  key: string;
  value: string;
  isSecret: boolean;
  showSecret: boolean;
}

interface MissingInfo {
  field: string;
  label: string;
  message: string;
  stepTarget: number;
}

const PLATFORMS = [
  { id: "nodejs", label: "Node.js", description: "قالب پیشنهادی MOCK برای Node.js؛ نسخهٔ runtime بررسی نشده است" },
  { id: "python", label: "Python / Django", description: "قالب پیشنهادی MOCK برای Python؛ وب‌سرور و نسخه باید جداگانه بررسی شوند" },
  { id: "docker", label: "Docker", description: "پیشنهاد بسته‌بندی با Docker؛ هیچ image یا Dockerfile اجرا نمی‌شود" },
  { id: "go", label: "Go", description: "قالب پیشنهادی MOCK برای برنامهٔ Go" },
  { id: "php", label: "PHP / Laravel", description: "قالب پیشنهادی MOCK برای PHP؛ نسخه و وب‌سرور تأیید نشده‌اند" },
  { id: "static", label: "Static", description: "قالب پیشنهادی MOCK برای وب‌سایت استاتیک" },
];

const HARDWARE_PLANS = [
  {
    id: "starter-256mb",
    label: "پایه (Starter)",
    ram: "۲۵۶ مگابایت رم",
    cpu: "۰.۵ هسته پردازنده",
    detail: "مناسب سرویس‌های سبک، وب‌هوک‌ها و محیط‌های آزمایشی",
  },
  {
    id: "standard-1gb",
    label: "استاندارد (Standard)",
    ram: "۱ گیگابایت رم",
    cpu: "۱ هسته پردازنده",
    detail: "پیشنهادی برای اپلیکیشن‌های تولیدی و بار کاری متعادل",
  },
  {
    id: "pro-2gb",
    label: "حرفه‌ای (Pro)",
    ram: "۲ گیگابایت رم",
    cpu: "۲ هسته پردازنده",
    detail: "برای برنامه‌های سنگین، پردازش تصویر و داده با ترافیک بالا",
  },
];

export function SetupPage({ c }: { c: SetupContext }) {
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const inFlight = useRef(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const submission = useRef<{ fingerprint: string; key: string } | null>(null);
  const [step, setStep] = useState<number>(1);
  const [serviceId, setServiceId] = useState<string>("my-node-app");
  const [platform, setPlatform] = useState<string>("nodejs");
  const [plan, setPlan] = useState<string>("standard-1gb");
  const [envVars, setEnvVars] = useState<EnvVar[]>([
    { id: "1", key: "NODE_ENV", value: "production", isSecret: false, showSecret: false },
    { id: "2", key: "PORT", value: "3000", isSecret: false, showSecret: false },
    { id: "3", key: "DATABASE_URL", value: "", isSecret: true, showSecret: false },
  ]);
  const [customDomain, setCustomDomain] = useState<string>("app.example.com");

  // Add environment variable
  const addEnvVar = () => {
    setEnvVars((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        key: "",
        value: "",
        isSecret: false,
        showSecret: false,
      },
    ]);
  };

  // Remove environment variable
  const removeEnvVar = (id: string) => {
    setEnvVars((prev) => prev.filter((item) => item.id !== id));
  };

  // Update environment variable
  const updateEnvVar = (id: string, updates: Partial<EnvVar>) => {
    setEnvVars((prev) =>
      prev.map((item) => (item.id === id ? { ...item, ...updates } : item)),
    );
  };

  // Immediate UI feedback; the server independently validates the saved brief.
  const computeMissingInfo = (): MissingInfo[] => {
    const missing: MissingInfo[] = [];

    // Service ID validation
    const trimmedId = serviceId.trim();
    if (!trimmedId) {
      missing.push({
        field: "service_id",
        label: "نام و شناسه سرویس",
        message: "وارد کردن شناسه یکتای سرویس الزامی است.",
        stepTarget: 1,
      });
    } else if (!/^[a-z0-9][a-z0-9-]{1,62}$/.test(trimmedId)) {
      missing.push({
        field: "service_id",
        label: "فرمت شناسه سرویس",
        message: "شناسه سرویس فقط می‌تواند شامل حروف کوچک انگلیسی، ارقام و خط تیره (-) باشد و باید بین ۲ تا ۶۳ کاراکتر باشد.",
        stepTarget: 1,
      });
    }

    // Platform validation
    if (!platform) {
      missing.push({
        field: "platform",
        label: "پلتفرم اجرایی",
        message: "انتخاب پلتفرم اجرایی برای راه‌اندازی الزامی است.",
        stepTarget: 1,
      });
    }

    // Plan validation
    if (!plan) {
      missing.push({
        field: "plan",
        label: "پلن منابع سخت‌افزاری",
        message: "انتخاب حداقل یک پلن سخت‌افزاری پیشنهادی الزامی است.",
        stepTarget: 1,
      });
    }

    // Domain validation (if provided)
    if (customDomain.trim()) {
      if (!validSetupDomain(customDomain.trim())) {
        missing.push({
          field: "custom_domain",
          label: "دامنه اختصاصی",
          message: "فرمت دامنه اختصاصی معتبر نیست (مثال استاندارد: app.example.com).",
          stepTarget: 2,
        });
      }
    }

    // Env vars validation
    envVars.forEach((v, idx) => {
      if (!v.key.trim() && v.value.trim()) {
        missing.push({
          field: `env_${v.id}`,
          label: `متغیر محیطی ردیف ${idx + 1}`,
          message: "نام متغیر محیطی دارای مقدار وارد نشده است.",
          stepTarget: 1,
        });
      }
    });
    const keys = envVars.map((v) => v.key.trim()).filter(Boolean);
    if (envVars.length > 30 || new Set(keys).size !== keys.length ||
        keys.some((key) => !/^[A-Z_][A-Z0-9_]{0,63}$/.test(key))) {
      missing.push({ field: "environment_keys", label: "نام متغیرهای محیطی",
        message: "حداکثر ۳۰ نام یکتا با حروف بزرگ انگلیسی، رقم و زیرخط مجاز است؛ نام نباید با رقم شروع شود.", stepTarget: 1 });
    }

    return missing;
  };

  const missingInfoList = computeMissingInfo();
  const isValid = missingInfoList.length === 0;

  const handleSendToApprovals = async () => {
    if (inFlight.current || !isValid) return;
    inFlight.current = true;
    setSubmitting(true);
    setSubmitError("");
    try {
      const brief: SetupBrief = {
        service_id: serviceId.trim(),
        platform: platform as SetupBrief["platform"],
        plan: plan as SetupBrief["plan"],
        custom_domain: customDomain.trim().toLowerCase(),
        environment_keys: envVars.map((item) => item.key.trim()).filter(Boolean).sort(),
      };
      // Values (including secrets) never enter the network payload or retry key.
      const fingerprint = JSON.stringify(brief);
      if (submission.current?.fingerprint !== fingerprint)
        submission.current = { fingerprint, key: crypto.randomUUID() };
      const saved = await submitSetup(brief, submission.current.key);
      if (!active.current) return;
      navigate("/approvals?setup=" + encodeURIComponent(saved.id));
      await c.reload();
    } catch {
      if (active.current) setSubmitError("ثبت برنامه انجام نشد یا نتیجه دریافت نشد. اطلاعات فرم حفظ شده است؛ برای دریافت نتیجه با همان شناسه دوباره تلاش کنید.");
    } finally {
      inFlight.current = false;
      if (active.current) setSubmitting(false);
    }
  };

  const selectedPlatform = PLATFORMS.find((p) => p.id === platform);
  const selectedPlan = HARDWARE_PLANS.find((p) => p.id === plan);

  return (
    <div className="setup-wizard-page">
      <Title
        title="راه‌اندازی و استقرار سرویس جدید"
        description="نیازسنجی استقرار، پیکربندی شبکه و دامنه، اعتبارسنجی اطلاعات و ساخت برنامه اقدام"
        action={
          <Badge tone="warning">
            <span className="demo-wide">MOCK · داده آزمایشی</span>
            <span className="demo-short">MOCK</span>
          </Badge>
        }
      />
      <Notice>این فرم فقط برنامهٔ آزمایشی MOCK ثبت می‌کند. پلن‌ها و مشخصات نمایشی، تأیید ظرفیت یا قیمت لیارا نیستند. هیچ سرویس، DNS یا گواهی SSL ایجاد نمی‌شود.</Notice>

      {/* Step Indicators */}
      <div className="steps" role="group" aria-label="مراحل راه‌اندازی سرویس">
        <button
          type="button"
          aria-current={step === 1 ? "step" : undefined}
          className={step === 1 ? "active" : ""}
          onClick={() => setStep(1)}
        >
          ۱ · نیازسنجی استقرار
        </button>
        <button
          type="button"
          aria-current={step === 2 ? "step" : undefined}
          className={step === 2 ? "active" : ""}
          onClick={() => setStep(2)}
        >
          ۲ · راهنمای دامنه و شبکه
        </button>
        <button
          type="button"
          aria-current={step === 3 ? "step" : undefined}
          className={step === 3 ? "active" : ""}
          onClick={() => setStep(3)}
        >
          ۳ · اعتبارسنجی و بررسی نقص‌ها
        </button>
        <button
          type="button"
          aria-current={step === 4 ? "step" : undefined}
          className={step === 4 ? "active" : ""}
          onClick={() => setStep(4)}
        >
          ۴ · برنامه اقدام و گیت تأیید
        </button>
      </div>

      {/* Step 1: Service Specification */}
      {step === 1 && (
        <section aria-label="مشخصات فنی">
          <Panel title="گام ۱: مشخصات فنی و نیازسنجی استقرار" icon={<Cube size={22} />}>
            <p className="panel-lead">
              شناسه یکتا، پلتفرم اجرایی، پلن سخت‌افزاری و متغیرهای پیکربندی برنامه را مشخص کنید.
            </p>

            <div className="form-grid">
              <label className="field">
                <span>نام سرویس / شناسه پروژه (service_id) *</span>
                <input
                  aria-label="نام سرویس"
                  value={serviceId}
                  onChange={(e) => setServiceId(e.target.value.toLowerCase())}
                  placeholder="مثلاً: my-node-app"
                  required
                  maxLength={63}
                />
                <small>تنها از حروف کوچک انگلیسی (a-z)، ارقام (0-9) و خط تیره (-) استفاده کنید.</small>
              </label>

              <label className="field">
                <span>پلتفرم اجرایی برنامه (Platform) *</span>
                <select
                  aria-label="پلتفرم سرویس"
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value)}
                  required
                >
                  {PLATFORMS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
                <small>{selectedPlatform?.description}</small>
              </label>
            </div>

            <div className="field">
              <span>پلن منابع سخت‌افزاری پیشنهادی (Hardware Plan) *</span>
              <div className="hardware-plans-grid" role="radiogroup" aria-label="پلن آزمایشی منابع">
                {HARDWARE_PLANS.map((p) => {
                  const isSelected = plan === p.id;
                  return (
                    <div
                      key={p.id}
                      className={`hardware-card ${isSelected ? "selected" : ""}`}
                      onClick={() => setPlan(p.id)}
                      role="radio"
                      aria-checked={isSelected}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === " " || e.key === "Enter") { e.preventDefault(); setPlan(p.id); }
                      }}
                    >
                      <div className="hardware-card-head">
                        <strong>{p.label}</strong>
                        {isSelected && <Check size={18} weight="bold" color="var(--cyan)" />}
                      </div>
                      <div className="hardware-specs">
                        <span>
                          <Cpu size={14} /> {p.cpu}
                        </span>
                        <span>
                          <Cube size={14} /> {p.ram}
                        </span>
                      </div>
                      <small>{p.detail}</small>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Environment Variables */}
            <div className="field">
              <div className="env-header">
                <span>متغیرهای محیطی و سکرت‌های برنامه (Environment Variables)</span>
                <button
                  type="button"
                  className="button outline small"
                  onClick={addEnvVar}
                  disabled={envVars.length >= 30}
                  aria-label="افزودن متغیر جدید"
                >
                  <Plus size={14} />
                  افزودن متغیر
                </button>
              </div>

              <div className="env-list">
                {envVars.map((env) => (
                  <div key={env.id} className="env-row">
                    <input
                      aria-label="نام کلید متغیر"
                      placeholder="KEY_NAME"
                      value={env.key}
                      onChange={(e) => updateEnvVar(env.id, { key: e.target.value })}
                      className="env-key"
                      maxLength={64}
                      autoComplete="off"
                    />
                    <div className="env-value-wrapper">
                      <input
                        aria-label="مقدار متغیر"
                        placeholder="VALUE"
                        type={env.isSecret && !env.showSecret ? "password" : "text"}
                        value={env.value}
                        onChange={(e) => updateEnvVar(env.id, { value: e.target.value })}
                        className="env-value"
                        autoComplete="off"
                        maxLength={4096}
                      />
                      {env.isSecret && (
                        <button
                          type="button"
                          className="icon-button env-toggle-secret"
                          aria-label={env.showSecret ? "مخفی‌سازی سکرت" : "نمایش سکرت"}
                          onClick={() => updateEnvVar(env.id, { showSecret: !env.showSecret })}
                        >
                          {env.showSecret ? <EyeSlash size={16} /> : <Eye size={16} />}
                        </button>
                      )}
                    </div>

                    <label className="env-secret-label">
                      <input
                        type="checkbox"
                        checked={env.isSecret}
                        onChange={(e) => updateEnvVar(env.id, { isSecret: e.target.checked })}
                      />
                      <span>سکرت (محرمانه)</span>
                    </label>

                    <button
                      type="button"
                      className="icon-button env-remove"
                      aria-label="حذف متغیر"
                      onClick={() => removeEnvVar(env.id)}
                    >
                      <Trash size={16} />
                    </button>
                  </div>
                ))}
              </div>
              <small>
                  مقادیر فقط در حافظهٔ فرم هستند و ارسال یا ذخیره نمی‌شوند؛ فقط نام متغیرها در برنامه ثبت می‌شود.
              </small>
            </div>

            <div className="button-row">
              <button
                type="button"
                className="button"
                onClick={() => setStep(2)}
              >
                ادامه به راهنمای دامنه و شبکه
                <ArrowLeft size={16} />
              </button>
            </div>
          </Panel>
        </section>
      )}

      {/* Step 2: Domain and Network Guidance */}
      {step === 2 && (
        <section aria-label="دامنه و شبکه">
          <Panel title="گام ۲: راهنمای دامنه اختصاصی و تنظیمات شبکه" icon={<Globe size={22} />}>
            <p className="panel-lead">
              نام دامنهٔ درخواستی را برای بررسی آینده وارد کنید. مالکیت دامنه، تنظیم DNS و دسترسی واقعی در این فرم بررسی نمی‌شود.
            </p>

            <div className="field">
              <span>دامنه اختصاصی مورد نظر (اختیاری)</span>
              <input
                aria-label="دامنه اختصاصی"
                value={customDomain}
                onChange={(e) => setCustomDomain(e.target.value.toLowerCase())}
                placeholder="مثلاً: app.example.com"
                maxLength={253}
              />
              <small>دامنه را بدون پروتکل http/https وارد کنید (مانند: service.mydomain.ir).</small>
            </div>

            {/* DNS Guidance Box */}
            <div className="dns-guidance-card">
              <div className="dns-guidance-head">
                <Globe size={20} color="var(--cyan)" />
                <strong>راهنمای تنظیم رکوردهای DNS در پنل دامنه شما</strong>
              </div>
              <p>
                نوع رکورد و مقصد باید پس از شناسایی سرویس واقعی از پنل ارائه‌دهنده دریافت شود. مقادیر زیر دستور تغییر DNS نیستند.
              </p>
              <div className="dns-record-box">
                <div className="dns-record-item">
                  <span className="dns-label">نوع رکورد (Type):</span>
                  <code className="dns-value">تأیید نشده</code>
                </div>
                <div className="dns-record-item">
                  <span className="dns-label">میزبان (Host / Name):</span>
                  <code className="dns-value">{customDomain || "تعیین نشده"}</code>
                </div>
                <div className="dns-record-item">
                  <span className="dns-label">مقدار / مقصد (Points to / Target):</span>
                  <code className="dns-value">در دسترس نیست</code>
                </div>
              </div>
            </div>

            {/* SSL Notice */}
            <div className="ssl-status-card">
              <div className="ssl-card-head">
                <Lock size={20} color="var(--cyan)" />
                <div>
                  <strong>وضعیت گواهی امنیتی SSL</strong>
                  <small>هیچ گواهی بررسی یا صادر نشده است</small>
                </div>
                <Badge tone="warning">تأیید نشده</Badge>
              </div>
              <p>
                فعال‌بودن SSL، شرایط صدور و هزینه باید برای سرویس واقعی جداگانه بررسی شود.
              </p>
            </div>

            <div className="button-row">
              <button
                type="button"
                className="button outline"
                onClick={() => setStep(1)}
              >
                <ArrowRight size={16} />
                بازگشت به مشخصات
              </button>
              <button
                type="button"
                className="button"
                onClick={() => setStep(3)}
              >
                اعتبارسنجی اطلاعات
                <ArrowLeft size={16} />
              </button>
            </div>
          </Panel>
        </section>
      )}

      {/* Step 3: Validation & Missing Information */}
      {step === 3 && (
        <section aria-label="اعتبارسنجی فرم">
          <Panel title="گام ۳: اعتبارسنجی و بررسی اطلاعات ناقص" icon={<WarningCircle size={22} />}>
            <p className="panel-lead">
              بررسی فرمت و کامل‌بودن فرم پیش از ارسال؛ سرور هنگام ثبت برنامه اعتبارسنجی مستقل انجام می‌دهد.
            </p>

            {/* Missing Information Cards */}
            {!isValid ? (
              <div className="missing-info-container">
                <Notice tone="danger">
                  <div>
                    <strong>هشدار: اطلاعات ناقص است (Missing Information)</strong>
                    <p>
                      برخی فیلدهای ضروری وارد نشده یا فرمت نادرست دارند. برای پیشبرد برنامه استقرار، موارد زیر را اصلاح نمایید:
                    </p>
                  </div>
                </Notice>

                <div className="missing-cards-list">
                  {missingInfoList.map((item, idx) => (
                    <div key={idx} className="missing-card">
                      <div className="missing-card-info">
                        <WarningCircle size={20} color="var(--danger)" />
                        <div>
                          <strong>{item.label}</strong>
                          <p>{item.message}</p>
                        </div>
                      </div>
                      <button
                        type="button"
                        className="button outline small"
                        onClick={() => setStep(item.stepTarget)}
                      >
                        اصلاح در گام {item.stepTarget}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="validation-success-box">
                <div className="success-banner">
                  <CheckCircle size={32} weight="fill" color="var(--cyan)" />
                  <div>
                    <strong>فرمت اطلاعات فرم معتبر است</strong>
                    <p>
                      اعتبارسنجی فرم به معنی تأیید ظرفیت، دسترسی، دامنه یا امکان استقرار نیست.
                    </p>
                  </div>
                </div>

                <div className="validation-summary-grid">
                  <div className="summary-item">
                    <span>شناسه سرویس:</span>
                    <strong>{serviceId}</strong>
                  </div>
                  <div className="summary-item">
                    <span>پلتفرم:</span>
                    <strong>{selectedPlatform?.label}</strong>
                  </div>
                  <div className="summary-item">
                    <span>پلن سخت‌افزاری:</span>
                    <strong>{selectedPlan?.label} ({selectedPlan?.ram})</strong>
                  </div>
                  <div className="summary-item">
                    <span>دامنه اتصال:</span>
                    <strong>{customDomain || "تعیین نشده"}</strong>
                  </div>
                  <div className="summary-item">
                    <span>تعداد متغیرهای محیطی:</span>
                    <strong>{envVars.filter((item) => item.key.trim()).length} نام پیشنهادی؛ هنوز ثبت نشده</strong>
                  </div>
                </div>
              </div>
            )}

            <div className="button-row">
              <button
                type="button"
                className="button outline"
                onClick={() => setStep(2)}
              >
                <ArrowRight size={16} />
                بازگشت به دامنه
              </button>
              <button
                type="button"
                className="button"
                disabled={!isValid}
                onClick={() => setStep(4)}
              >
                مشاهده برنامه اقدام و گیت تأیید
                <ArrowLeft size={16} />
              </button>
            </div>
          </Panel>
        </section>
      )}

      {/* Step 4: Action Plan & Guardrails */}
      {step === 4 && (
        <section aria-label="برنامه پیشنهادی">
          <Panel title="گام ۴: برنامه اقدام و اعلان اختیارات (Action Plan & Guardrails)" icon={<ShieldCheck size={22} />}>
            <p className="panel-lead">
              مراحل مرحله‌ای استقرار سرویس در قالب گردش کار زیر تعریف شده است.
            </p>

            <Notice>
              این برنامه MOCK است. فقط نام متغیرهای محیطی ذخیره می‌شود؛ مقادیر و سکرت‌ها ارسال نمی‌شوند.
              Gate فعلی ایجاد سرویس را پشتیبانی نمی‌کند؛ برنامه در کارتابل با وضعیت مسدود ثبت خواهد شد.
              منابع، قیمت‌ها و قابلیت‌های استقرار در لیارا تأیید نشده‌اند.
            </Notice>
            {submitError && <p role="alert">{submitError}</p>}
            {/* Workflow Steps Timeline */}
            <div className="workflow-plan-box">
              <h3 className="workflow-title">برنامه گام‌به‌گام استقرار (Workflow Steps)</h3>
              <ol className="setup-workflow-list">
                <li className="workflow-step-item">
                  <span className="step-badge">۱</span>
                  <div className="step-content">
                    <strong>بررسی مشخصات و اعتبارسنجی نیازمندی‌ها (review_brief)</strong>
                    <p>
                      تطبیق پیکربندی سرویس <code>{serviceId}</code> روی پلتفرم <code>{selectedPlatform?.label}</code> با منابع <code>{selectedPlan?.label}</code>.
                    </p>
                  </div>
                </li>

                <li className="workflow-step-item">
                  <span className="step-badge">۲</span>
                  <div className="step-content">
                    <strong>بررسی آیندهٔ ظرفیت و پشتیبانی منابع (review_resources)</strong>
                    <p>این گام اجرا نمی‌شود؛ ظرفیت و پشتیبانی منابع باید جداگانه بررسی شود.</p>
                  </div>
                </li>

                <li className="workflow-step-item">
                  <span className="step-badge">۳</span>
                  <div className="step-content">
                    <strong>پیکربندی امن متغیرهای محیطی و سکرت‌ها (configure_env)</strong>
                    <p>
                      ثبت نام {envVars.length} متغیر محیطی؛ مقدارها ارسال یا ذخیره نمی‌شوند و نیاز به مسیر امن جداگانه دارند.
                    </p>
                  </div>
                </li>

                <li className="workflow-step-item">
                  <span className="step-badge">۴</span>
                  <div className="step-content">
                    <strong>پیکربندی مسیر دامنه اختصاصی و گواهی امنیتی (configure_domain_ssl)</strong>
                    <p>
                      تنظیم شبکه و گواهی انجام نمی‌شود؛ روش اتصال دامنه باید در مرحله اجرای واقعی بررسی شود.
                    </p>
                  </div>
                </li>

                <li className="workflow-step-item">
                  <span className="step-badge">۵</span>
                  <div className="step-content">
                    <strong>ثبت درخواست در کارتابل تأیید عملیات (request_approval)</strong>
                    <p>ثبت برنامه با محدودیت صریح؛ هیچ مجوز اجرایی صادر نمی‌شود.</p>
                  </div>
                </li>
              </ol>
            </div>

            {/* Crucial Security Guardrail Card */}
            <div className="guardrail-alert-box">
              <div className="guardrail-alert-head">
                <div className="guardrail-badge-wrap">
                  <ShieldCheck size={26} weight="fill" color="var(--danger)" />
                  <Badge tone="danger">توجه امنیتی</Badge>
                </div>
                <strong>
                  دستیار اینفراپایلوت اجازه ایجاد یا دیپلوی خودکار بدون تأیید نهایی شما را ندارد. هیچ هزینه‌ای بدون تأیید ایجاد نخواهد شد.
                </strong>
              </div>
              <p className="guardrail-description">
                طبق اصل عدم دسترسی خودکار به زیرساخت (Zero-Touch Infrastructure Guardrail)، این برنامه استقرار در مرحله پیش‌نویس متوقف می‌شود و هیچ عملیات واقعی زیرساختی بدون ثبت تأیید صریح در کارتابل تأیید عملیات (Approval Gate) اجرا نخواهد گردید.
              </p>
            </div>

            <div className="button-row">
              <button
                type="button"
                className="button outline"
                onClick={() => setStep(3)}
              >
                <ArrowRight size={16} />
                بازگشت به اعتبارسنجی
              </button>
              <button
                type="button"
                className="button action-approval-button"
                disabled={!isValid || submitting || c.busy}
                onClick={() => void handleSendToApprovals()}
              >
                <ShieldCheck size={18} weight="bold" />
                {submitting ? "در حال ثبت برنامه…" : "ارسال برنامه به کارتابل تأیید عملیات"}
              </button>
            </div>
          </Panel>
        </section>
      )}
    </div>
  );
}
