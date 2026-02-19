import { useEffect, useMemo, useState } from "react";
import {
  askQuestion,
  assignUserTenant,
  createTenant,
  createUser,
  decideApproval,
  fetchApprovals,
  fetchAudit,
  getApprovalResult,
  getIngestJob,
  ingestFile,
  listTenants,
  listUsers,
  login,
  logout
} from "./api";
import { detectLocale, type Locale, t } from "./i18n";
import type {
  ApprovalResponse,
  AuditRecord,
  IngestJobResponse,
  RetrievedChunk,
  Tenant,
  UserAccount
} from "./types";
import "./styles.css";

type Panel = "workbench" | "approvals" | "audit" | "admin";

type StatusMessage = {
  key: string;
  params?: Record<string, string | number>;
};

const PANELS: Array<{ id: Panel; labelKey: string; descKey: string }> = [
  { id: "workbench", labelKey: "panel.workbench", descKey: "panel.workbenchDesc" },
  { id: "approvals", labelKey: "panel.approvals", descKey: "panel.approvalsDesc" },
  { id: "audit", labelKey: "panel.audit", descKey: "panel.auditDesc" },
  { id: "admin", labelKey: "panel.admin", descKey: "panel.adminDesc" }
];

const panelDomId = (id: Panel) => `panel-${id}`;
const tabDomId = (id: Panel) => `tab-${id}`;

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const roleTone = (role: string | null) => {
  if (!role) return "muted";
  if (role === "admin") return "good";
  if (role === "auditor") return "warn";
  return "neutral";
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

  return (
    <div className="shell">
      <a href="#main-content" className="skip-link">
        {tt("skip.main")}
      </a>

      <header className="hero" role="banner">
        <div className="hero-main">
          <div className="hero-topbar">
            <p className="eyebrow">{tt("hero.eyebrow")}</p>
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

          <h1>{tt("hero.title")}</h1>
          <p>{tt("hero.desc")}</p>
          <div className="tag-row" aria-label="capabilities">
            <span className="tag">{tt("hero.tag.rbac")}</span>
            <span className="tag">{tt("hero.tag.multitenant")}</span>
            <span className="tag">{tt("hero.tag.approval")}</span>
            <span className="tag">{tt("hero.tag.audit")}</span>
          </div>
        </div>

        <aside className="hero-side" aria-label="session metrics">
          <div className={`status-chip status-${roleTone(role)}`}>
            {isAuthenticated ? tt("auth.as", { role: role || "" }) : tt("auth.guest")}
          </div>
          <p className="status-copy" aria-live="polite">
            {tt(status.key, status.params)}
          </p>
          <div className="metrics-grid">
            <article>
              <h4>{tt("metrics.pendingApprovals")}</h4>
              <strong>{approvals.length}</strong>
            </article>
            <article>
              <h4>{tt("metrics.auditEvents")}</h4>
              <strong>{auditLogs.length}</strong>
            </article>
            <article>
              <h4>{tt("metrics.tenants")}</h4>
              <strong>{tenants.length}</strong>
            </article>
            <article>
              <h4>{tt("metrics.users")}</h4>
              <strong>{users.length}</strong>
            </article>
          </div>
        </aside>
      </header>

      <div className="workspace-layout">
        <aside className="rail">
          <section className="panel auth-panel" aria-label="auth form">
            <h2>{tt("session.title")}</h2>
            <div className="field">
              <label htmlFor="login-username">{tt("session.username")}</label>
              <input
                id="login-username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
              />
            </div>
            <div className="field">
              <label htmlFor="login-password">{tt("session.password")}</label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
              />
            </div>
            <div className="field">
              <label htmlFor="tenant-id">{tt("session.tenantScope")}</label>
              <input
                id="tenant-id"
                value={tenantId}
                onChange={(event) => setTenantId(event.target.value)}
              />
            </div>
            <div className="actions">
              <button
                onClick={handleLogin}
                disabled={isAuthenticated || busyAction === "login"}
                data-testid="login-button"
              >
                {busyAction === "login" ? tt("session.signingIn") : tt("session.signIn")}
              </button>
              <button
                className="ghost"
                onClick={handleLogout}
                disabled={!isAuthenticated || busyAction === "logout"}
              >
                {tt("session.signOut")}
              </button>
            </div>
          </section>

          <section className="panel nav-panel" aria-label="workspace tabs">
            <h2>{tt("workspace.title")}</h2>
            <div className="tab-list" role="tablist" aria-label={tt("workspace.title")}>
              {PANELS.map((panel) => (
                <button
                  id={tabDomId(panel.id)}
                  key={panel.id}
                  className={`tab-btn ${activePanel === panel.id ? "active" : ""}`}
                  onClick={() => setActivePanel(panel.id)}
                  type="button"
                  role="tab"
                  aria-selected={activePanel === panel.id}
                  aria-controls={panelDomId(panel.id)}
                  data-testid={panel.id === "admin" ? "tab-admin" : undefined}
                >
                  <span>{tt(panel.labelKey)}</span>
                  <small>{tt(panel.descKey)}</small>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <main id="main-content" className="content" tabIndex={-1}>
          {activePanel === "workbench" && (
            <section
              className="panel stack"
              id={panelDomId("workbench")}
              role="tabpanel"
              aria-labelledby={tabDomId("workbench")}
            >
              <div className="split-grid">
                <article className="card">
                  <h3>{tt("workbench.ingestTitle")}</h3>
                  <p className="muted">{tt("workbench.ingestDesc")}</p>
                  <div className="field">
                    <label htmlFor="ingest-file">{tt("workbench.document")}</label>
                    <input
                      id="ingest-file"
                      type="file"
                      onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                    />
                  </div>
                  <div className="actions">
                    <button
                      onClick={handleIngest}
                      disabled={!isAuthenticated || !isAdmin || !file || busyAction === "ingest"}
                    >
                      {busyAction === "ingest"
                        ? tt("workbench.submitting")
                        : tt("workbench.submitIngest")}
                    </button>
                  </div>
                  {!isAdmin && isAuthenticated && (
                    <p className="muted">{tt("workbench.adminRequiredIngest")}</p>
                  )}
                  {latestJob && (
                    <div className="note">
                      <strong>{tt("workbench.job")}:</strong> {latestJob.job_id}
                      <br />
                      <strong>{tt("workbench.jobStatus")}:</strong> {latestJob.status}
                    </div>
                  )}
                </article>

                <article className="card">
                  <h3>{tt("workbench.askTitle")}</h3>
                  <p className="muted">{tt("workbench.askDesc")}</p>
                  <div className="field">
                    <label htmlFor="question">{tt("workbench.question")}</label>
                    <textarea
                      id="question"
                      rows={4}
                      value={question}
                      onChange={(event) => setQuestion(event.target.value)}
                      placeholder={tt("workbench.questionPlaceholder")}
                      data-testid="question-input"
                    />
                  </div>
                  <div className="actions">
                    <button
                      onClick={handleAsk}
                      disabled={!isAuthenticated || !question || busyAction === "ask"}
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
                    <p className="muted">
                      {tt("workbench.approvalId")}: {approvalId}
                    </p>
                  )}
                </article>
              </div>

              <article className="card">
                <h3>{tt("workbench.responseTitle")}</h3>
                <p data-testid="answer-content">{answer || tt("workbench.noAnswer")}</p>
                <div className="context-list">
                  {retrieved.length === 0 ? (
                    <p className="muted">{tt("workbench.noChunks")}</p>
                  ) : (
                    retrieved.map((item, index) => (
                      <article key={`${index}-${item.score}`} className="context-item">
                        <span className="score">{item.score.toFixed(3)}</span>
                        <p>{item.text}</p>
                        {item.source && <small>{item.source}</small>}
                      </article>
                    ))
                  )}
                </div>
              </article>
            </section>
          )}

          {activePanel === "approvals" && (
            <section
              className="panel stack"
              id={panelDomId("approvals")}
              role="tabpanel"
              aria-labelledby={tabDomId("approvals")}
            >
              <article className="card">
                <div className="row">
                  <div>
                    <h3>{tt("approvals.title")}</h3>
                    <p className="muted">{tt("approvals.desc")}</p>
                  </div>
                  <button
                    className="ghost"
                    onClick={handleLoadApprovals}
                    disabled={!isAuthenticated || !canApprove || busyAction === "approvals"}
                  >
                    {tt("approvals.refresh")}
                  </button>
                </div>

                <div className="field">
                  <label htmlFor="approval-note">{tt("approvals.note")}</label>
                  <input
                    id="approval-note"
                    value={approvalNote}
                    onChange={(event) => setApprovalNote(event.target.value)}
                  />
                </div>

                {!canApprove && isAuthenticated && (
                  <p className="muted">{tt("approvals.noPermission")}</p>
                )}

                <div className="approval-list">
                  {approvals.length === 0 ? (
                    <p className="muted">{tt("approvals.empty")}</p>
                  ) : (
                    approvals.map((approval) => (
                      <article className="approval-item" key={approval.approval_id}>
                        <p className="muted">{approval.approval_id}</p>
                        <p>
                          <strong>{tt("approvals.question")}:</strong> {approval.question}
                        </p>
                        <p>
                          <strong>{tt("approvals.draft")}:</strong> {approval.draft_answer}
                        </p>
                        <div className="actions">
                          <button
                            onClick={() => handleDecision(approval, true)}
                            disabled={!canApprove}
                          >
                            {tt("approvals.approve")}
                          </button>
                          <button
                            className="ghost"
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
              </article>
            </section>
          )}

          {activePanel === "audit" && (
            <section
              className="panel stack"
              id={panelDomId("audit")}
              role="tabpanel"
              aria-labelledby={tabDomId("audit")}
            >
              <article className="card">
                <div className="row">
                  <div>
                    <h3>{tt("audit.title")}</h3>
                    <p className="muted">{tt("audit.desc")}</p>
                  </div>
                  <button
                    className="ghost"
                    onClick={handleAudit}
                    disabled={!isAuthenticated || busyAction === "audit"}
                  >
                    {tt("audit.refresh")}
                  </button>
                </div>

                {auditLogs.length === 0 ? (
                  <p className="muted">{tt("audit.empty")}</p>
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
                            <td>{log.action}</td>
                            <td>{log.input_text}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </article>
            </section>
          )}

          {activePanel === "admin" && (
            <section
              className="panel stack"
              id={panelDomId("admin")}
              role="tabpanel"
              aria-labelledby={tabDomId("admin")}
              data-testid="admin-panel"
            >
              <article className="card">
                <h3>{tt("admin.title")}</h3>
                {!isAdmin && isAuthenticated && (
                  <p className="muted">{tt("admin.noPermission")}</p>
                )}

                <div className="split-grid">
                  <section className="sub-card">
                    <div className="row">
                      <h4>{tt("admin.tenants")}</h4>
                      <button
                        className="ghost"
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
                        onChange={(event) => setTenantName(event.target.value)}
                      />
                    </div>
                    <button
                      onClick={handleCreateTenant}
                      disabled={!isAdmin || !tenantName || busyAction === "tenant-create"}
                    >
                      {tt("admin.createTenant")}
                    </button>
                    <ul className="list">
                      {tenants.map((tenant) => (
                        <li key={tenant.tenant_id}>
                          <strong>{tenant.name}</strong>
                          <span>{tenant.tenant_id}</span>
                        </li>
                      ))}
                    </ul>
                  </section>

                  <section className="sub-card">
                    <div className="row">
                      <h4>{tt("admin.users")}</h4>
                      <button
                        className="ghost"
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
                        onChange={(event) => setNewUserName(event.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="new-user-password">{tt("admin.newPassword")}</label>
                      <input
                        id="new-user-password"
                        type="password"
                        value={newUserPassword}
                        onChange={(event) => setNewUserPassword(event.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="new-user-role">{tt("admin.role")}</label>
                      <select
                        id="new-user-role"
                        value={newUserRole}
                        onChange={(event) => setNewUserRole(event.target.value)}
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
                        onChange={(event) => setNewUserDefaultTenant(event.target.value)}
                      />
                    </div>
                    <button
                      onClick={handleCreateUser}
                      disabled={!isAdmin || !newUserName || !newUserPassword || busyAction === "user-create"}
                    >
                      {tt("admin.createUser")}
                    </button>

                    <div className="field compact-top">
                      <label htmlFor="assign-user-id">{tt("admin.assignUserId")}</label>
                      <input
                        id="assign-user-id"
                        value={assignUserId}
                        onChange={(event) => setAssignUserId(event.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="assign-tenant-id">{tt("admin.assignTenantId")}</label>
                      <input
                        id="assign-tenant-id"
                        value={assignTenantId}
                        onChange={(event) => setAssignTenantId(event.target.value)}
                      />
                    </div>
                    <button
                      className="ghost"
                      onClick={handleAssignTenant}
                      disabled={!isAdmin || !assignUserId || !assignTenantId || busyAction === "tenant-assign"}
                    >
                      {tt("admin.assignTenant")}
                    </button>

                    <ul className="list" data-testid="admin-users-list">
                      {users.map((entry) => (
                        <li key={entry.user_id}>
                          <strong>
                            {entry.username} ({entry.role})
                          </strong>
                          <span>{entry.tenant_ids.join(", ") || tt("admin.noTenants")}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                </div>
              </article>
            </section>
          )}
        </main>
      </div>

      <footer className="status-bar" aria-live="polite">
        {tt(status.key, status.params)}
      </footer>
    </div>
  );
}
