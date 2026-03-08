import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  askQuestion,
  assignUserTenant,
  chatStream,
  createTenant,
  createUser,
  decideApproval,
  deleteDocument,
  fetchApprovals,
  fetchAudit,
  fetchHealthCheck,
  fetchLogs,
  fetchMetrics,
  getApprovalResult,
  getIngestJob,
  ingestFile,
  listDocuments,
  listTenants,
  listUsers,
  login,
  logout
} from "./api";
import { detectLocale, type Locale, t } from "./i18n";
import type {
  ApprovalResponse,
  AuditRecord,
  DocumentInfo,
  IngestJobResponse,
  LogEntry,
  MetricsSummary,
  RetrievedChunk,
  Tenant,
  UserAccount
} from "./types";
import "./styles.css";

type Panel = "workbench" | "approvals" | "audit" | "admin" | "monitoring";

type StatusMessage = {
  key: string;
  params?: Record<string, string | number>;
};

const PANELS: Array<{ id: Panel; labelKey: string }> = [
  { id: "workbench", labelKey: "panel.workbench" },
  { id: "approvals", labelKey: "panel.approvals" },
  { id: "audit", labelKey: "panel.audit" },
  { id: "admin", labelKey: "panel.admin" },
  { id: "monitoring", labelKey: "panel.monitoring" }
];

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/* ── Inline SVG Icons ───────────────────────────────────── */
const IconChat = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const IconShield = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

const IconClipboard = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
    <rect x="8" y="2" width="8" height="4" rx="1" />
    <path d="M9 14h6M9 18h6M9 10h6" />
  </svg>
);

const IconSettings = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

const IconMonitor = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
);

const IconLogo = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="12 2 2 7 12 12 22 7 12 2" />
    <polyline points="2 17 12 22 22 17" />
    <polyline points="2 12 12 17 22 12" />
  </svg>
);

const NAV_ICONS: Record<Panel, () => React.ReactElement> = {
  workbench: IconChat,
  approvals: IconShield,
  audit: IconClipboard,
  admin: IconSettings,
  monitoring: IconMonitor
};

export default function App() {
  const initialLocale = detectLocale();

  const [locale, setLocale] = useState<Locale>(initialLocale);
  const [username, setUsername] = useState("demo");
  const [password, setPassword] = useState("demo123");
  const [tenantId, setTenantId] = useState("default");
  const [token, setToken] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusMessage>({ key: "status.ready" });
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const [activePanel, setActivePanel] = useState<Panel>("workbench");

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [retrieved, setRetrieved] = useState<RetrievedChunk[]>([]);
  const [approvalId, setApprovalId] = useState<string | null>(null);

  const [useStreaming, setUseStreaming] = useState(false);
  const [streamController, setStreamController] = useState<AbortController | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [latestJob, setLatestJob] = useState<IngestJobResponse | null>(null);

  const [auditLogs, setAuditLogs] = useState<AuditRecord[]>([]);
  const [approvals, setApprovals] = useState<ApprovalResponse[]>([]);
  const [approvalNote, setApprovalNote] = useState("");

  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantName, setTenantName] = useState("");

  const [users, setUsers] = useState<UserAccount[]>([]);
  const [newUserName, setNewUserName] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserRole, setNewUserRole] = useState("user");
  const [newUserDefaultTenant, setNewUserDefaultTenant] = useState("");
  const [assignUserId, setAssignUserId] = useState("");
  const [assignTenantId, setAssignTenantId] = useState("");

  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [rewrittenQuery, setRewrittenQuery] = useState<string | null>(null);
  const [judgeCompleted, setJudgeCompleted] = useState(false);

  // Monitoring state
  const [monitorMetrics, setMonitorMetrics] = useState<MetricsSummary | null>(null);
  const [monitorLogs, setMonitorLogs] = useState<LogEntry[]>([]);
  const [monitorLogCounts, setMonitorLogCounts] = useState<Record<string, number>>({});
  const [monitorHealth, setMonitorHealth] = useState<Record<string, unknown> | null>(null);
  const [monitorLogLevel, setMonitorLogLevel] = useState<string>("");
  const [monitorLogSearch, setMonitorLogSearch] = useState<string>("");
  const [monitorAutoRefresh, setMonitorAutoRefresh] = useState(true);
  const [monitorTab, setMonitorTab] = useState<"dashboard" | "logs" | "health">("dashboard");
  const [expandedLogIdx, setExpandedLogIdx] = useState<number | null>(null);
  const monitorTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isAuthenticated = useMemo(() => Boolean(token), [token]);
  const isAdmin = role === "admin";
  const canApprove = role === "admin" || role === "auditor";

  const tt = (key: string, params?: Record<string, string | number>) => t(locale, key, params);

  const formatTimestamp = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US");
  };

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const runAction = async (action: string, fn: () => Promise<void>) => {
    setBusyAction(action);
    try {
      await fn();
    } finally {
      setBusyAction(null);
    }
  };

  const pollIngestJob = async (jobId: string) => {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const job = await getIngestJob(jobId, token);
      setLatestJob(job);
      if (job.status === "completed") {
        setStatus({ key: "status.ingestCompleted", params: { count: job.chunks_indexed } });
        return;
      }
      if (job.status === "failed") {
        setStatus({
          key: "status.ingestFailed",
          params: { reason: job.error_message || "Unknown error" }
        });
        return;
      }
      await delay(1500);
    }
    setStatus({ key: "status.ingestRunning" });
  };

  const handleLogin = async () => {
    await runAction("login", async () => {
      try {
        setStatus({ key: "status.signingIn" });
        const result = await login(username, password);
        setToken(result.access_token);
        setRole(result.role);
        if (result.default_tenant_id) {
          setTenantId(result.default_tenant_id);
        }
        setStatus({ key: "status.signedIn", params: { role: result.role } });
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.loginFailed" });
      }
    });
  };

  const handleLogout = async () => {
    await runAction("logout", async () => {
      try {
        await logout(token);
      } catch (error) {
        console.error(error);
      }
      setToken(null);
      setRole(null);
      setAnswer("");
      setRetrieved([]);
      setApprovalId(null);
      setStatus({ key: "status.signedOut" });
    });
  };

  const handleIngest = async () => {
    if (!file || !isAuthenticated || !isAdmin) return;
    await runAction("ingest", async () => {
      try {
        setStatus({ key: "status.ingestSubmitting" });
        const result = await ingestFile(file, tenantId, token);
        setStatus({ key: "status.ingestQueued", params: { jobId: result.job_id } });
        await pollIngestJob(result.job_id);
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.ingestSubmitFailed" });
      }
    });
  };

  const handleAsk = async () => {
    if (!question || !isAuthenticated) return;
    await runAction("ask", async () => {
      try {
        setRewrittenQuery(null);
        setJudgeCompleted(false);
        setStatus({ key: "status.retrievalRunning" });
        const result = await askQuestion(question, tenantId, token);
        setRetrieved(result.retrieved);
        setApprovalId(result.approval_id ?? null);

        if (result.status === "pending_approval" && result.approval_id) {
          setAnswer(tt("workbench.pendingApprovalAnswer"));
          setStatus({ key: "status.approvalRequired" });
        } else {
          setAnswer(result.answer);
          setStatus({ key: "status.answerReady" });
        }
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.chatFailed" });
      }
    });
  };

  const handleAskStream = () => {
    if (!question || !isAuthenticated) return;
    if (streamController) streamController.abort();

    setAnswer("");
    setRetrieved([]);
    setApprovalId(null);
    setRewrittenQuery(null);
    setJudgeCompleted(false);
    setBusyAction("ask");
    setStatus({ key: "status.retrievalRunning" });

    let accumulated = "";
    const controller = chatStream(question, tenantId, token, (event, data) => {
      switch (event) {
        case "rewrite_done":
          setRewrittenQuery((data.rewritten_query as string) || null);
          break;
        case "judge_done":
          setJudgeCompleted(true);
          break;
        case "retrieve_done":
          setRetrieved(
            ((data.retrieved as Array<{ text: string; score: number; source: string; page_numbers?: number[] }>) || []).map(
              (r) => ({ text: r.text, score: r.score, source: r.source, page_numbers: r.page_numbers })
            )
          );
          setStatus({ key: "status.retrievalRunning" });
          break;
        case "generate_start":
          setStatus({ key: "status.generating" });
          break;
        case "token":
          accumulated += (data.text as string) || "";
          setAnswer(accumulated);
          break;
        case "policy_blocked":
          setAnswer(
            "The generated response was withheld due to policy checks. Please contact an administrator."
          );
          setStatus({ key: "status.policyBlocked" });
          setBusyAction(null);
          break;
        case "policy_passed":
          setStatus({ key: "status.answerReady" });
          break;
        case "approval_required":
          setApprovalId((data.approval_id as string) || null);
          setAnswer(tt("workbench.pendingApprovalAnswer"));
          setStatus({ key: "status.approvalRequired" });
          setBusyAction(null);
          break;
        case "done":
          setAnswer((data.answer as string) || accumulated);
          setStatus({ key: "status.answerReady" });
          setBusyAction(null);
          break;
      }
    });
    setStreamController(controller);
  };

  const handleRefreshApprovalResult = async () => {
    if (!approvalId || !isAuthenticated) return;
    await runAction("approval-refresh", async () => {
      try {
        const result = await getApprovalResult(approvalId, tenantId, token);
        if (result.status === "approved" && result.final_answer) {
          setAnswer(result.final_answer);
          setStatus({ key: "status.approvalCompleted" });
        } else if (result.status === "rejected") {
          setAnswer(tt("workbench.rejectedAnswer"));
          setStatus({ key: "status.approvalRejected" });
        } else {
          setStatus({ key: "status.approvalPending" });
        }
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.approvalFetchFailed" });
      }
    });
  };

  const handleAudit = async () => {
    if (!isAuthenticated) return;
    await runAction("audit", async () => {
      try {
        const result = await fetchAudit(token, 100);
        setAuditLogs(result);
        setStatus({ key: "status.auditLoaded", params: { count: result.length } });
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.auditLoadFailed" });
      }
    });
  };

  const handleLoadApprovals = async () => {
    if (!isAuthenticated) return;
    await runAction("approvals", async () => {
      try {
        const result = await fetchApprovals("pending", tenantId, token);
        setApprovals(result);
        setStatus({ key: "status.approvalsLoaded", params: { count: result.length } });
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.approvalsLoadFailed" });
      }
    });
  };

  const handleDecision = async (approval: ApprovalResponse, approved: boolean) => {
    if (!isAuthenticated || !canApprove) return;
    await runAction(`decision-${approval.approval_id}`, async () => {
      try {
        await decideApproval(approval.approval_id, approved, approvalNote, token);
        setStatus({ key: approved ? "status.approvalAccepted" : "status.approvalRejected" });
        await handleLoadApprovals();
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.approvalDecisionFailed" });
      }
    });
  };

  const handleLoadTenants = async () => {
    if (!isAuthenticated || !isAdmin) return;
    await runAction("tenants", async () => {
      try {
        const result = await listTenants(token);
        setTenants(result);
        setStatus({ key: "status.tenantsLoaded", params: { count: result.length } });
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.tenantsLoadFailed" });
      }
    });
  };

  const handleCreateTenant = async () => {
    if (!isAuthenticated || !isAdmin || !tenantName) return;
    await runAction("tenant-create", async () => {
      try {
        await createTenant(tenantName, token);
        setTenantName("");
        await handleLoadTenants();
        setStatus({ key: "status.tenantCreated" });
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.tenantCreateFailed" });
      }
    });
  };

  const handleLoadUsers = async () => {
    if (!isAuthenticated || !isAdmin) return;
    await runAction("users", async () => {
      try {
        const result = await listUsers(token);
        setUsers(result);
        setStatus({ key: "status.usersLoaded", params: { count: result.length } });
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.usersLoadFailed" });
      }
    });
  };

  const handleCreateUser = async () => {
    if (!isAuthenticated || !isAdmin || !newUserName || !newUserPassword) return;
    await runAction("user-create", async () => {
      try {
        await createUser(
          newUserName,
          newUserPassword,
          newUserRole,
          newUserDefaultTenant || null,
          token
        );
        setNewUserName("");
        setNewUserPassword("");
        setStatus({ key: "status.userCreated" });
        await handleLoadUsers();
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.userCreateFailed" });
      }
    });
  };

  const handleAssignTenant = async () => {
    if (!isAuthenticated || !isAdmin || !assignUserId || !assignTenantId) return;
    await runAction("tenant-assign", async () => {
      try {
        await assignUserTenant(assignUserId, assignTenantId, token);
        setAssignUserId("");
        setAssignTenantId("");
        setStatus({ key: "status.tenantAssigned" });
        await handleLoadUsers();
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.tenantAssignFailed" });
      }
    });
  };

  const handleLoadDocuments = async () => {
    if (!isAuthenticated || !isAdmin) return;
    await runAction("documents", async () => {
      try {
        const result = await listDocuments(tenantId, token);
        setDocuments(result);
        setStatus({ key: "status.docsLoaded", params: { count: result.length } });
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.docsLoadFailed" });
      }
    });
  };

  const handleDeleteDocument = async (doc: DocumentInfo) => {
    if (!isAuthenticated || !isAdmin) return;
    const confirmed = window.confirm(tt("docs.confirmDelete", { name: doc.filename }));
    if (!confirmed) return;
    await runAction(`doc-delete-${doc.document_id}`, async () => {
      try {
        await deleteDocument(doc.document_id, token);
        setStatus({ key: "status.docDeleted" });
        await handleLoadDocuments();
      } catch (error) {
        console.error(error);
        setStatus({ key: "status.docDeleteFailed" });
      }
    });
  };

  // ── Monitoring data fetching ──────────────────────────────
  const loadMonitoringData = useCallback(async () => {
    if (!isAuthenticated || !isAdmin) return;
    try {
      const [metricsData, logsData, healthData] = await Promise.all([
        fetchMetrics(token),
        fetchLogs(token, {
          limit: 200,
          level: monitorLogLevel || undefined,
          search: monitorLogSearch || undefined,
        }),
        fetchHealthCheck(token),
      ]);
      setMonitorMetrics(metricsData);
      setMonitorLogs(logsData.entries);
      setMonitorLogCounts(logsData.counts);
      setMonitorHealth(healthData);
    } catch (err) {
      console.error("Failed to load monitoring data:", err);
    }
  }, [isAuthenticated, isAdmin, token, monitorLogLevel, monitorLogSearch]);

  useEffect(() => {
    if (activePanel === "monitoring" && isAdmin) {
      loadMonitoringData();
    }
  }, [activePanel, loadMonitoringData, isAdmin]);

  useEffect(() => {
    if (activePanel === "monitoring" && monitorAutoRefresh && isAdmin) {
      monitorTimerRef.current = setInterval(loadMonitoringData, 10000);
      return () => {
        if (monitorTimerRef.current) clearInterval(monitorTimerRef.current);
      };
    }
    if (monitorTimerRef.current) {
      clearInterval(monitorTimerRef.current);
      monitorTimerRef.current = null;
    }
  }, [activePanel, monitorAutoRefresh, isAdmin, loadMonitoringData]);

  const panelTitle = PANELS.find((p) => p.id === activePanel);
  const isBusy = busyAction !== null;

  /* ═══════════════════════════════════════════════════════════
     LOGIN PAGE (unauthenticated)
     ═══════════════════════════════════════════════════════════ */
  if (!isAuthenticated) {
    return (
      <div className="app-shell">
        <a href="#main-content" className="skip-link">{tt("skip.main")}</a>
        <div className="login-page">
          <div className="login-card animate-in">
            <div className="login-header">
              <div className="login-logo">
                <IconLogo />
              </div>
              <h2>Complyra</h2>
              <p>{tt("hero.desc")}</p>
            </div>

            <div className="field">
              <label htmlFor="login-username">{tt("session.username")}</label>
              <input
                id="login-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="demo"
              />
            </div>
            <div className="field">
              <label htmlFor="login-password">{tt("session.password")}</label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
            <div className="field">
              <label htmlFor="tenant-id">{tt("session.tenantScope")}</label>
              <input
                id="tenant-id"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                placeholder="default"
              />
            </div>

            <div className="login-actions">
              <button
                className="btn-primary"
                onClick={handleLogin}
                disabled={busyAction === "login"}
                data-testid="login-button"
              >
                {busyAction === "login" ? tt("session.signingIn") : tt("session.signIn")}
              </button>
            </div>

            {status.key !== "status.ready" && status.key !== "status.signedOut" && (
              <p className="muted" style={{ marginTop: 12, textAlign: "center" }}>
                {tt(status.key, status.params)}
              </p>
            )}

            <div style={{ display: "flex", justifyContent: "center", marginTop: 16 }}>
              <div className="lang-switch" role="group" aria-label={tt("lang.switch")}>
                <button
                  type="button"
                  className={`lang-btn ${locale === "en" ? "active" : ""}`}
                  aria-pressed={locale === "en"}
                  onClick={() => setLocale("en")}
                  data-testid="lang-en"
                >
                  {tt("lang.en")}
                </button>
                <button
                  type="button"
                  className={`lang-btn ${locale === "zh" ? "active" : ""}`}
                  aria-pressed={locale === "zh"}
                  onClick={() => setLocale("zh")}
                  data-testid="lang-zh"
                >
                  {tt("lang.zh")}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ═══════════════════════════════════════════════════════════
     MAIN APP (authenticated)
     ═══════════════════════════════════════════════════════════ */
  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">{tt("skip.main")}</a>

      {/* ── Sidebar ──────────────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-icon"><IconLogo /></div>
          <div>
            <h1>Complyra</h1>
            <small>{tt("hero.eyebrow")}</small>
          </div>
        </div>

        <div className="sidebar-section">
          <div className="sidebar-label">{tt("workspace.title")}</div>
          {PANELS.map((panel) => {
            const Icon = NAV_ICONS[panel.id];
            return (
              <button
                key={panel.id}
                className={`nav-item ${activePanel === panel.id ? "active" : ""}`}
                onClick={() => setActivePanel(panel.id)}
                type="button"
                role="tab"
                aria-selected={activePanel === panel.id}
                data-testid={panel.id === "admin" ? "tab-admin" : undefined}
              >
                <Icon />
                <span>{tt(panel.labelKey)}</span>
                {panel.id === "approvals" && approvals.length > 0 && (
                  <span className="nav-badge">{approvals.length}</span>
                )}
              </button>
            );
          })}
        </div>

        <div className="sidebar-spacer" />

        <div className="sidebar-divider" />

        <div className="sidebar-metrics">
          <div className="sidebar-metric">
            <div className="metric-label">{tt("metrics.pendingApprovals")}</div>
            <div className="metric-value">{approvals.length}</div>
          </div>
          <div className="sidebar-metric">
            <div className="metric-label">{tt("metrics.auditEvents")}</div>
            <div className="metric-value">{auditLogs.length}</div>
          </div>
          <div className="sidebar-metric">
            <div className="metric-label">{tt("metrics.tenants")}</div>
            <div className="metric-value">{tenants.length}</div>
          </div>
          <div className="sidebar-metric">
            <div className="metric-label">{tt("metrics.users")}</div>
            <div className="metric-value">{users.length}</div>
          </div>
        </div>

        <div className="sidebar-divider" />

        <div className="sidebar-user">
          <div className="user-info">
            <div className="user-avatar">
              {(username || "U")[0].toUpperCase()}
            </div>
            <div>
              <div className="user-name">{username}</div>
              <div className="user-role">{role}</div>
            </div>
          </div>
          <button
            className="btn-logout"
            onClick={handleLogout}
            disabled={busyAction === "logout"}
          >
            {tt("session.signOut")}
          </button>
        </div>
      </aside>

      {/* ── Main Content ─────────────────────────────────────── */}
      <div className="main-content">
        <header className="topbar">
          <h2 className="topbar-title">{panelTitle ? tt(panelTitle.labelKey) : ""}</h2>
          <div className="topbar-spacer" />
          <div className={`topbar-status ${isBusy ? "busy" : ""}`} aria-live="polite">
            {tt(status.key, status.params)}
            {isBusy && (
              <span className="streaming-dot">
                <span /><span /><span />
              </span>
            )}
          </div>
          <div className="lang-switch" role="group" aria-label={tt("lang.switch")}>
            <button
              type="button"
              className={`lang-btn ${locale === "en" ? "active" : ""}`}
              aria-pressed={locale === "en"}
              onClick={() => setLocale("en")}
              data-testid="lang-en"
            >
              {tt("lang.en")}
            </button>
            <button
              type="button"
              className={`lang-btn ${locale === "zh" ? "active" : ""}`}
              aria-pressed={locale === "zh"}
              onClick={() => setLocale("zh")}
              data-testid="lang-zh"
            >
              {tt("lang.zh")}
            </button>
          </div>
        </header>

        <main id="main-content" className="content-area" tabIndex={-1}>
          {/* ── Workbench ──────────────────────────────────── */}
          {activePanel === "workbench" && (
            <div className="stack animate-in">
              <div className="grid-2">
                <div className="card">
                  <h3>{tt("workbench.ingestTitle")}</h3>
                  <p className="card-desc">{tt("workbench.ingestDesc")}</p>
                  <div className="field">
                    <label htmlFor="ingest-file">{tt("workbench.document")}</label>
                    <input
                      id="ingest-file"
                      type="file"
                      onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    />
                  </div>
                  <div className="actions">
                    <button
                      onClick={handleIngest}
                      disabled={!isAdmin || !file || busyAction === "ingest"}
                    >
                      {busyAction === "ingest"
                        ? tt("workbench.submitting")
                        : tt("workbench.submitIngest")}
                    </button>
                  </div>
                  {!isAdmin && (
                    <p className="muted" style={{ marginTop: 8 }}>{tt("workbench.adminRequiredIngest")}</p>
                  )}
                  {latestJob && (
                    <div className="note">
                      <strong>{tt("workbench.job")}:</strong> {latestJob.job_id}
                      <br />
                      <strong>{tt("workbench.jobStatus")}:</strong>{" "}
                      <span className={`badge badge-${latestJob.status === "completed" ? "success" : latestJob.status === "failed" ? "warning" : "info"}`}>
                        {latestJob.status}
                      </span>
                    </div>
                  )}
                </div>

                <div className="card">
                  <h3>{tt("workbench.askTitle")}</h3>
                  <p className="card-desc">{tt("workbench.askDesc")}</p>
                  <div className="field">
                    <label htmlFor="question">{tt("workbench.question")}</label>
                    <textarea
                      id="question"
                      rows={3}
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder={tt("workbench.questionPlaceholder")}
                      data-testid="question-input"
                    />
                  </div>
                  <div className="field">
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={useStreaming}
                        onChange={(e) => setUseStreaming(e.target.checked)}
                      />
                      {tt("workbench.streamingMode")}
                    </label>
                  </div>
                  <div className="actions">
                    <button
                      onClick={useStreaming ? handleAskStream : handleAsk}
                      disabled={!question || busyAction === "ask"}
                      data-testid="run-query-button"
                    >
                      {busyAction === "ask" ? tt("workbench.thinking") : tt("workbench.runQuery")}
                    </button>
                    <button
                      className="ghost"
                      onClick={handleRefreshApprovalResult}
                      disabled={!approvalId || busyAction === "approval-refresh"}
                    >
                      {tt("workbench.refreshApproval")}
                    </button>
                  </div>
                  {approvalId && (
                    <p className="muted" style={{ marginTop: 8 }}>
                      {tt("workbench.approvalId")}: <code>{approvalId}</code>
                    </p>
                  )}
                </div>
              </div>

              <div className="card response-card">
                <h3>{tt("workbench.responseTitle")}</h3>
                <div style={{ marginTop: 12 }}>
                  {answer ? (
                    <p className={`response-text ${busyAction === "ask" ? "typing-cursor" : ""}`} data-testid="answer-content">
                      {answer}
                    </p>
                  ) : (
                    <p className="response-empty muted" data-testid="answer-content">{tt("workbench.noAnswer")}</p>
                  )}
                </div>

                {rewrittenQuery && (
                  <div className="query-rewrite">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8" />
                      <line x1="21" y1="21" x2="16.65" y2="16.65" />
                    </svg>
                    <span>{tt("query.searchedFor", { query: rewrittenQuery })}</span>
                    {judgeCompleted && (
                      <span className="judge-badge">{tt("query.judged")}</span>
                    )}
                  </div>
                )}

                <div className="context-section">
                  <h4>{tt("citation.contextTitle")}</h4>
                  {retrieved.length === 0 ? (
                    <p className="muted">{tt("workbench.noChunks")}</p>
                  ) : (
                    <div className="context-list">
                      {retrieved.map((item, index) => {
                        const pct = Math.round(item.score * 100);
                        return (
                          <article key={`${index}-${item.score}`} className="context-item">
                            <div className="citation-meta">
                              {item.source && (
                                <span className="citation-source">
                                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                                    <polyline points="14 2 14 8 20 8" />
                                  </svg>
                                  {item.source}
                                </span>
                              )}
                              {item.page_numbers && item.page_numbers.length > 0 && (
                                <span className="citation-pages">
                                  {tt("citation.page")}
                                  {item.page_numbers.length === 1
                                    ? item.page_numbers[0]
                                    : `${item.page_numbers[0]}-${item.page_numbers[item.page_numbers.length - 1]}`}
                                </span>
                              )}
                              <div className="relevance-bar-wrap">
                                <span className="relevance-bar-label">{pct}%</span>
                                <div className="relevance-bar">
                                  <div className="relevance-bar-fill" style={{ width: `${pct}%` }} />
                                </div>
                              </div>
                            </div>
                            <p>{item.text}</p>
                          </article>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── Approvals ──────────────────────────────────── */}
          {activePanel === "approvals" && (
            <div className="stack animate-in">
              <div className="card">
                <div className="card-header">
                  <div>
                    <h3>{tt("approvals.title")}</h3>
                    <p className="card-desc">{tt("approvals.desc")}</p>
                  </div>
                  <button
                    className="ghost"
                    onClick={handleLoadApprovals}
                    disabled={!canApprove || busyAction === "approvals"}
                  >
                    {tt("approvals.refresh")}
                  </button>
                </div>

                <div className="field">
                  <label htmlFor="approval-note">{tt("approvals.note")}</label>
                  <input
                    id="approval-note"
                    value={approvalNote}
                    onChange={(e) => setApprovalNote(e.target.value)}
                    placeholder={locale === "zh" ? "可选：添加审批备注" : "Optional: add a note"}
                  />
                </div>

                {!canApprove && (
                  <p className="muted" style={{ marginTop: 12 }}>{tt("approvals.noPermission")}</p>
                )}

                <div className="approval-list">
                  {approvals.length === 0 ? (
                    <p className="muted">{tt("approvals.empty")}</p>
                  ) : (
                    approvals.map((approval) => (
                      <article className="approval-item" key={approval.approval_id}>
                        <div className="approval-id">{approval.approval_id}</div>
                        <div>
                          <strong>{tt("approvals.question")}</strong>
                          <p>{approval.question}</p>
                        </div>
                        <div>
                          <strong>{tt("approvals.draft")}</strong>
                          <p>{approval.draft_answer}</p>
                        </div>
                        <div className="approval-actions">
                          <button
                            className="btn-success btn-sm"
                            onClick={() => handleDecision(approval, true)}
                            disabled={!canApprove}
                          >
                            {tt("approvals.approve")}
                          </button>
                          <button
                            className="btn-danger btn-sm"
                            onClick={() => handleDecision(approval, false)}
                            disabled={!canApprove}
                          >
                            {tt("approvals.reject")}
                          </button>
                        </div>
                      </article>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── Audit ──────────────────────────────────────── */}
          {activePanel === "audit" && (
            <div className="stack animate-in">
              <div className="card">
                <div className="card-header">
                  <div>
                    <h3>{tt("audit.title")}</h3>
                    <p className="card-desc">{tt("audit.desc")}</p>
                  </div>
                  <button
                    className="ghost"
                    onClick={handleAudit}
                    disabled={busyAction === "audit"}
                  >
                    {tt("audit.refresh")}
                  </button>
                </div>

                {auditLogs.length === 0 ? (
                  <p className="muted" style={{ marginTop: 16 }}>{tt("audit.empty")}</p>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <caption className="sr-only">Audit logs</caption>
                      <thead>
                        <tr>
                          <th>{tt("audit.time")}</th>
                          <th>{tt("audit.tenant")}</th>
                          <th>{tt("audit.user")}</th>
                          <th>{tt("audit.action")}</th>
                          <th>{tt("audit.input")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {auditLogs.map((log) => (
                          <tr key={log.id}>
                            <td>{formatTimestamp(log.timestamp)}</td>
                            <td>{log.tenant_id}</td>
                            <td>{log.user}</td>
                            <td>
                              <span className="badge badge-info">{log.action}</span>
                            </td>
                            <td>{log.input_text}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Admin ──────────────────────────────────────── */}
          {activePanel === "admin" && (
            <div className="stack animate-in" data-testid="admin-panel">
              {!isAdmin && (
                <div className="card">
                  <p className="muted">{tt("admin.noPermission")}</p>
                </div>
              )}

              {/* Documents */}
              <div className="card">
                <div className="card-header">
                  <div>
                    <h3>{tt("docs.title")}</h3>
                    <p className="card-desc">{tt("docs.desc")}</p>
                  </div>
                  <button
                    className="ghost btn-sm"
                    onClick={handleLoadDocuments}
                    disabled={!isAdmin || busyAction === "documents"}
                  >
                    {tt("docs.refresh")}
                  </button>
                </div>

                {documents.length === 0 ? (
                  <p className="muted" style={{ marginTop: 16 }}>{tt("docs.empty")}</p>
                ) : (
                  <ul className="doc-list">
                    {documents.map((doc) => (
                      <li key={doc.document_id} className="doc-item">
                        <div className="doc-item-info">
                          <div className="doc-item-name">{doc.filename}</div>
                          <div className="doc-item-meta">{tt("docs.chunks", { count: doc.chunk_count })}</div>
                        </div>
                        <button
                          className="btn-danger btn-sm"
                          onClick={() => handleDeleteDocument(doc)}
                          disabled={!isAdmin || busyAction === `doc-delete-${doc.document_id}`}
                        >
                          {tt("docs.delete")}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="grid-2">
                {/* Tenants */}
                <div className="sub-card">
                  <div className="row">
                    <h4>{tt("admin.tenants")}</h4>
                    <button
                      className="ghost btn-sm"
                      onClick={handleLoadTenants}
                      disabled={!isAdmin || busyAction === "tenants"}
                    >
                      {tt("admin.load")}
                    </button>
                  </div>
                  <div className="field">
                    <label htmlFor="tenant-name">{tt("admin.newTenant")}</label>
                    <input
                      id="tenant-name"
                      value={tenantName}
                      onChange={(e) => setTenantName(e.target.value)}
                    />
                  </div>
                  <div className="actions">
                    <button
                      onClick={handleCreateTenant}
                      disabled={!isAdmin || !tenantName || busyAction === "tenant-create"}
                    >
                      {tt("admin.createTenant")}
                    </button>
                  </div>
                  <ul className="item-list">
                    {tenants.map((tenant) => (
                      <li key={tenant.tenant_id}>
                        <strong>{tenant.name}</strong>
                        <span>{tenant.tenant_id}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Users */}
                <div className="sub-card">
                  <div className="row">
                    <h4>{tt("admin.users")}</h4>
                    <button
                      className="ghost btn-sm"
                      onClick={handleLoadUsers}
                      disabled={!isAdmin || busyAction === "users"}
                      data-testid="load-users-button"
                    >
                      {tt("admin.load")}
                    </button>
                  </div>
                  <div className="field">
                    <label htmlFor="new-user-name">{tt("admin.newUser")}</label>
                    <input
                      id="new-user-name"
                      value={newUserName}
                      onChange={(e) => setNewUserName(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="new-user-password">{tt("admin.newPassword")}</label>
                    <input
                      id="new-user-password"
                      type="password"
                      value={newUserPassword}
                      onChange={(e) => setNewUserPassword(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="new-user-role">{tt("admin.role")}</label>
                    <select
                      id="new-user-role"
                      value={newUserRole}
                      onChange={(e) => setNewUserRole(e.target.value)}
                    >
                      <option value="admin">admin</option>
                      <option value="user">user</option>
                      <option value="auditor">auditor</option>
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="new-user-default-tenant">{tt("admin.defaultTenant")}</label>
                    <input
                      id="new-user-default-tenant"
                      value={newUserDefaultTenant}
                      onChange={(e) => setNewUserDefaultTenant(e.target.value)}
                    />
                  </div>
                  <div className="actions">
                    <button
                      onClick={handleCreateUser}
                      disabled={!isAdmin || !newUserName || !newUserPassword || busyAction === "user-create"}
                    >
                      {tt("admin.createUser")}
                    </button>
                  </div>

                  <div className="compact-top">
                    <div className="field">
                      <label htmlFor="assign-user-id">{tt("admin.assignUserId")}</label>
                      <input
                        id="assign-user-id"
                        value={assignUserId}
                        onChange={(e) => setAssignUserId(e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="assign-tenant-id">{tt("admin.assignTenantId")}</label>
                      <input
                        id="assign-tenant-id"
                        value={assignTenantId}
                        onChange={(e) => setAssignTenantId(e.target.value)}
                      />
                    </div>
                    <div className="actions">
                      <button
                        className="ghost"
                        onClick={handleAssignTenant}
                        disabled={!isAdmin || !assignUserId || !assignTenantId || busyAction === "tenant-assign"}
                      >
                        {tt("admin.assignTenant")}
                      </button>
                    </div>
                  </div>

                  <ul className="item-list" data-testid="admin-users-list">
                    {users.map((entry) => (
                      <li key={entry.user_id}>
                        <strong>
                          {entry.username} ({entry.role})
                        </strong>
                        <span>{entry.tenant_ids.join(", ") || tt("admin.noTenants")}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* ── Monitoring ─────────────────────────────────── */}
          {activePanel === "monitoring" && (
            <div className="stack animate-in">
              {!isAdmin && (
                <div className="card"><p className="muted">{tt("admin.noPermission")}</p></div>
              )}

              {/* Tab Bar */}
              <div className="monitor-tabs">
                {(["dashboard", "logs", "health"] as const).map((tab) => (
                  <button
                    key={tab}
                    className={`monitor-tab ${monitorTab === tab ? "active" : ""}`}
                    onClick={() => setMonitorTab(tab)}
                  >
                    {tt(`monitor.tab.${tab}`)}
                  </button>
                ))}
                <div className="monitor-tabs-spacer" />
                <label className="monitor-auto-refresh">
                  <input
                    type="checkbox"
                    checked={monitorAutoRefresh}
                    onChange={(e) => setMonitorAutoRefresh(e.target.checked)}
                  />
                  {tt("monitor.autoRefresh")}
                </label>
                <button className="ghost btn-sm" onClick={loadMonitoringData}>
                  {tt("monitor.refresh")}
                </button>
              </div>

              {/* Dashboard Tab */}
              {monitorTab === "dashboard" && monitorMetrics && (
                <>
                  {/* Stat Cards Row */}
                  <div className="monitor-stats-grid">
                    <div className="monitor-stat-card">
                      <div className="monitor-stat-label">{tt("monitor.totalRequests")}</div>
                      <div className="monitor-stat-value">{Math.round(monitorMetrics.http.total_requests)}</div>
                    </div>
                    <div className={`monitor-stat-card ${monitorMetrics.http.error_rate > 0.05 ? "stat-danger" : ""}`}>
                      <div className="monitor-stat-label">{tt("monitor.errorRate")}</div>
                      <div className="monitor-stat-value">{(monitorMetrics.http.error_rate * 100).toFixed(2)}%</div>
                    </div>
                    <div className="monitor-stat-card">
                      <div className="monitor-stat-label">{tt("monitor.avgLatency")}</div>
                      <div className="monitor-stat-value">{(monitorMetrics.http.avg_latency * 1000).toFixed(0)}ms</div>
                    </div>
                    <div className={`monitor-stat-card ${monitorMetrics.ingestion.queue_depth > 50 ? "stat-warning" : ""}`}>
                      <div className="monitor-stat-label">{tt("monitor.queueDepth")}</div>
                      <div className="monitor-stat-value">{monitorMetrics.ingestion.queue_depth}</div>
                    </div>
                    <div className="monitor-stat-card">
                      <div className="monitor-stat-label">{tt("monitor.ragQueries")}</div>
                      <div className="monitor-stat-value">{Math.round(monitorMetrics.rag.query_count)}</div>
                    </div>
                    <div className="monitor-stat-card">
                      <div className="monitor-stat-label">{tt("monitor.docsIngested")}</div>
                      <div className="monitor-stat-value">{Math.round(monitorMetrics.ingestion.documents_total)}</div>
                    </div>
                  </div>

                  {/* LLM & RAG Cards */}
                  <div className="grid-2">
                    <div className="card">
                      <h3>{tt("monitor.llmPerformance")}</h3>
                      <div className="monitor-kv-grid">
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.llmCalls")}</span>
                          <span className="monitor-kv-value">{Math.round(monitorMetrics.llm.call_count)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.llmAvgDuration")}</span>
                          <span className="monitor-kv-value">{monitorMetrics.llm.avg_duration.toFixed(2)}s</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.llmErrors")}</span>
                          <span className={`monitor-kv-value ${monitorMetrics.llm.error_count > 0 ? "text-danger" : ""}`}>{monitorMetrics.llm.error_count}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.llmTokens")}</span>
                          <span className="monitor-kv-value">{Math.round(monitorMetrics.llm.tokens_generated)}</span>
                        </div>
                      </div>
                      {Object.keys(monitorMetrics.llm.by_provider).length > 0 && (
                        <div className="monitor-provider-list">
                          <h4>{tt("monitor.byProvider")}</h4>
                          {Object.entries(monitorMetrics.llm.by_provider).map(([provider, stats]) => (
                            <div key={provider} className="monitor-provider-item">
                              <span className="badge badge-info">{provider}</span>
                              <span>{Math.round(stats.count)} calls</span>
                              <span>{stats.avg.toFixed(2)}s avg</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="card">
                      <h3>{tt("monitor.ragPipeline")}</h3>
                      <div className="monitor-kv-grid">
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.ragQueries")}</span>
                          <span className="monitor-kv-value">{Math.round(monitorMetrics.rag.query_count)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.ragAvgDuration")}</span>
                          <span className="monitor-kv-value">{monitorMetrics.rag.avg_duration.toFixed(2)}s</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.vectorSearches")}</span>
                          <span className="monitor-kv-value">{Math.round(monitorMetrics.retrieval.search_count)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.embeddingTexts")}</span>
                          <span className="monitor-kv-value">{Math.round(monitorMetrics.embedding.texts_processed)}</span>
                        </div>
                      </div>
                      {Object.keys(monitorMetrics.rag.by_status).length > 0 && (
                        <div className="monitor-provider-list">
                          <h4>{tt("monitor.queryStatus")}</h4>
                          {Object.entries(monitorMetrics.rag.by_status).map(([status, count]) => (
                            <div key={status} className="monitor-provider-item">
                              <span className={`badge ${status === "success" ? "badge-success" : status === "blocked" ? "badge-warning" : "badge-info"}`}>{status}</span>
                              <span>{Math.round(count)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Ingestion & Policy Cards */}
                  <div className="grid-2">
                    <div className="card">
                      <h3>{tt("monitor.ingestion")}</h3>
                      <div className="monitor-kv-grid">
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.docsIngested")}</span>
                          <span className="monitor-kv-value">{Math.round(monitorMetrics.ingestion.success_count)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.ingestErrors")}</span>
                          <span className={`monitor-kv-value ${monitorMetrics.ingestion.error_count > 0 ? "text-danger" : ""}`}>{Math.round(monitorMetrics.ingestion.error_count)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.chunksTotal")}</span>
                          <span className="monitor-kv-value">{Math.round(monitorMetrics.ingestion.chunks_total)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.avgIngestTime")}</span>
                          <span className="monitor-kv-value">{monitorMetrics.ingestion.avg_duration.toFixed(2)}s</span>
                        </div>
                      </div>
                      {Object.keys(monitorMetrics.ingestion.by_type).length > 0 && (
                        <div className="monitor-provider-list">
                          <h4>{tt("monitor.byFileType")}</h4>
                          {Object.entries(monitorMetrics.ingestion.by_type).map(([type, count]) => (
                            <div key={type} className="monitor-provider-item">
                              <span className="badge badge-info">{type}</span>
                              <span>{Math.round(count)} docs</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="card">
                      <h3>{tt("monitor.outputPolicy")}</h3>
                      <div className="monitor-kv-grid">
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.policyTotal")}</span>
                          <span className="monitor-kv-value">{Math.round(monitorMetrics.policy.total)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.policyPassed")}</span>
                          <span className="monitor-kv-value" style={{ color: "var(--c-success)" }}>{Math.round(monitorMetrics.policy.passed)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.policyBlocked")}</span>
                          <span className={`monitor-kv-value ${monitorMetrics.policy.blocked > 0 ? "text-danger" : ""}`}>{Math.round(monitorMetrics.policy.blocked)}</span>
                        </div>
                        <div className="monitor-kv">
                          <span className="monitor-kv-label">{tt("monitor.httpErrors")}</span>
                          <span className={`monitor-kv-value ${monitorMetrics.http.error_count > 0 ? "text-danger" : ""}`}>{Math.round(monitorMetrics.http.error_count)}</span>
                        </div>
                      </div>
                      {Object.keys(monitorMetrics.http.by_status).length > 0 && (
                        <div className="monitor-provider-list">
                          <h4>{tt("monitor.httpByStatus")}</h4>
                          {Object.entries(monitorMetrics.http.by_status).map(([code, count]) => (
                            <div key={code} className="monitor-provider-item">
                              <span className={`badge ${code.startsWith("2") ? "badge-success" : code.startsWith("4") ? "badge-warning" : code.startsWith("5") ? "badge-danger" : "badge-info"}`}>{code}</span>
                              <span>{Math.round(count)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </>
              )}

              {/* Logs Tab */}
              {monitorTab === "logs" && (
                <div className="card">
                  <div className="monitor-log-toolbar">
                    <select
                      className="monitor-log-select"
                      value={monitorLogLevel}
                      onChange={(e) => setMonitorLogLevel(e.target.value)}
                    >
                      <option value="">{tt("monitor.allLevels")}</option>
                      <option value="ERROR">ERROR</option>
                      <option value="WARNING">WARNING</option>
                      <option value="INFO">INFO</option>
                      <option value="DEBUG">DEBUG</option>
                    </select>
                    <input
                      className="monitor-log-search"
                      type="text"
                      placeholder={tt("monitor.searchLogs")}
                      value={monitorLogSearch}
                      onChange={(e) => setMonitorLogSearch(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && loadMonitoringData()}
                    />
                    <button className="ghost btn-sm" onClick={loadMonitoringData}>{tt("monitor.filter")}</button>
                    <div className="monitor-log-counts">
                      {Object.entries(monitorLogCounts).map(([level, count]) =>
                        count > 0 ? (
                          <span key={level} className={`badge badge-sm ${level === "ERROR" ? "badge-danger" : level === "WARNING" ? "badge-warning" : "badge-info"}`}>
                            {level}: {count}
                          </span>
                        ) : null
                      )}
                    </div>
                  </div>

                  <div className="monitor-log-list">
                    {monitorLogs.length === 0 ? (
                      <p className="muted" style={{ padding: 16 }}>{tt("monitor.noLogs")}</p>
                    ) : (
                      monitorLogs.map((log, idx) => (
                        <div key={idx} className="monitor-log-entry" onClick={() => setExpandedLogIdx(expandedLogIdx === idx ? null : idx)}>
                          <div className="monitor-log-row">
                            <span className="monitor-log-time">
                              {new Date(log.timestamp * 1000).toLocaleTimeString(locale === "zh" ? "zh-CN" : "en-US", { hour12: false })}
                            </span>
                            <span className={`badge badge-sm ${log.level === "ERROR" ? "badge-danger" : log.level === "WARNING" ? "badge-warning" : "badge-info"}`}>
                              {log.level}
                            </span>
                            <span className="monitor-log-logger">{log.logger}</span>
                            <span className="monitor-log-msg">{log.message}</span>
                          </div>
                          {expandedLogIdx === idx && (
                            <div className="monitor-log-detail">
                              {log.request_id && <div><strong>Request ID:</strong> {log.request_id}</div>}
                              {Object.entries(log.extra).map(([k, v]) => (
                                <div key={k}><strong>{k}:</strong> {v}</div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* Health Tab */}
              {monitorTab === "health" && monitorHealth && (
                <div className="card">
                  <h3>{tt("monitor.systemHealth")}</h3>
                  <div className="monitor-health-info">
                    <span className="badge badge-info">{tt("monitor.version")}: {String((monitorHealth as Record<string, unknown>).version ?? "")}</span>
                    <span className="badge badge-info">{tt("monitor.environment")}: {String((monitorHealth as Record<string, unknown>).environment ?? "")}</span>
                    <span className="badge badge-info">LLM: {String((monitorHealth as Record<string, unknown>).llm_provider ?? "")}</span>
                    <span className="badge badge-info">Embedding: {String((monitorHealth as Record<string, unknown>).embedding_provider ?? "")}</span>
                  </div>
                  <div className="monitor-health-grid">
                    {Object.entries(((monitorHealth as Record<string, unknown>).checks ?? {}) as Record<string, Record<string, unknown>>).map(([component, detail]) => (
                      <div key={component} className={`monitor-health-card ${detail.status ? "health-up" : "health-down"}`}>
                        <div className="monitor-health-indicator">{detail.status ? "\u2705" : "\u274C"}</div>
                        <div className="monitor-health-name">{component.charAt(0).toUpperCase() + component.slice(1)}</div>
                        <div className="monitor-health-status">{detail.status ? "UP" : "DOWN"}</div>
                        {detail.latency_ms !== undefined && (
                          <div className="monitor-health-latency">{String(detail.latency_ms)}ms</div>
                        )}
                        {"error" in detail && detail.error ? (
                          <div className="monitor-health-error">{String(detail.error).slice(0, 60)}</div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
