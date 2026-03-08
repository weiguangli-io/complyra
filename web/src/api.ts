import axios from "axios";
import type {
  ApprovalResponse,
  AuditRecord,
  ChatResponse,
  DocumentInfo,
  IngestJobResponse,
  IngestSubmitResponse,
  LogsResponse,
  MetricsSummary,
  Tenant,
  TokenResponse,
  UserAccount
} from "./types";

const apiBase = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

const client = axios.create({
  baseURL: apiBase,
  timeout: 45000,
  withCredentials: true
});

function authHeaders(token?: string | null) {
  if (!token) {
    return {};
  }
  return { Authorization: `Bearer ${token}` };
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  const response = await client.post<TokenResponse>("/auth/login", { username, password });
  return response.data;
}

export async function logout(token?: string | null): Promise<void> {
  await client.post("/auth/logout", {}, { headers: authHeaders(token) });
}

export async function ingestFile(
  file: File,
  tenantId: string,
  token?: string | null
): Promise<IngestSubmitResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await client.post<IngestSubmitResponse>("/ingest/file", form, {
    headers: {
      ...authHeaders(token),
      "X-Tenant-ID": tenantId
    }
  });
  return response.data;
}

export async function getIngestJob(jobId: string, token?: string | null): Promise<IngestJobResponse> {
  const response = await client.get<IngestJobResponse>(`/ingest/jobs/${jobId}`, {
    headers: authHeaders(token)
  });
  return response.data;
}

export async function askQuestion(
  question: string,
  tenantId: string,
  token?: string | null
): Promise<ChatResponse> {
  const response = await client.post<ChatResponse>(
    "/chat/",
    { question },
    {
      headers: {
        ...authHeaders(token),
        "X-Tenant-ID": tenantId
      }
    }
  );
  return response.data;
}

export async function fetchAudit(token?: string | null, limit = 50): Promise<AuditRecord[]> {
  const response = await client.get<AuditRecord[]>(`/audit/?limit=${limit}`, {
    headers: authHeaders(token)
  });
  return response.data;
}

export async function fetchApprovals(
  status: string | undefined,
  tenantId: string | undefined,
  token?: string | null
): Promise<ApprovalResponse[]> {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  if (tenantId) params.append("tenant_id", tenantId);
  const response = await client.get<ApprovalResponse[]>(`/approvals/?${params.toString()}`, {
    headers: authHeaders(token)
  });
  return response.data;
}

export async function decideApproval(
  approvalId: string,
  approved: boolean,
  note: string,
  token?: string | null
): Promise<ApprovalResponse> {
  const response = await client.post<ApprovalResponse>(
    `/approvals/${approvalId}/decision`,
    { approved, note },
    { headers: authHeaders(token) }
  );
  return response.data;
}

export async function getApprovalResult(
  approvalId: string,
  tenantId: string,
  token?: string | null
): Promise<ApprovalResponse> {
  const response = await client.get<ApprovalResponse>(`/approvals/${approvalId}/result`, {
    headers: {
      ...authHeaders(token),
      "X-Tenant-ID": tenantId
    }
  });
  return response.data;
}

export async function listTenants(token?: string | null): Promise<Tenant[]> {
  const response = await client.get<Tenant[]>("/tenants/", { headers: authHeaders(token) });
  return response.data;
}

export async function createTenant(name: string, token?: string | null): Promise<Tenant> {
  const response = await client.post<Tenant>(
    "/tenants/",
    { name },
    { headers: authHeaders(token) }
  );
  return response.data;
}

export async function listUsers(token?: string | null): Promise<UserAccount[]> {
  const response = await client.get<UserAccount[]>("/users/", { headers: authHeaders(token) });
  return response.data;
}

export async function createUser(
  username: string,
  password: string,
  role: string,
  defaultTenantId: string | null,
  token?: string | null
): Promise<UserAccount> {
  const response = await client.post<UserAccount>(
    "/users/",
    { username, password, role, default_tenant_id: defaultTenantId },
    { headers: authHeaders(token) }
  );
  return response.data;
}

export async function assignUserTenant(userId: string, tenantId: string, token?: string | null): Promise<void> {
  await client.post(
    `/users/${userId}/tenants`,
    { tenant_id: tenantId },
    { headers: authHeaders(token) }
  );
}

export async function listDocuments(tenantId: string, token?: string | null): Promise<DocumentInfo[]> {
  const response = await client.get<DocumentInfo[]>("/documents/", {
    headers: {
      ...authHeaders(token),
      "X-Tenant-ID": tenantId
    }
  });
  return response.data;
}

export async function deleteDocument(documentId: string, token?: string | null): Promise<void> {
  await client.delete(`/documents/${documentId}`, {
    headers: authHeaders(token)
  });
}

/* ── Admin Monitoring ───────────────────────────────────── */

export async function fetchMetrics(token?: string | null): Promise<MetricsSummary> {
  const response = await client.get<MetricsSummary>("/admin/monitoring/metrics", {
    headers: authHeaders(token)
  });
  return response.data;
}

export async function fetchLogs(
  token?: string | null,
  params?: { limit?: number; level?: string; search?: string; since_minutes?: number }
): Promise<LogsResponse> {
  const query = new URLSearchParams();
  if (params?.limit) query.append("limit", String(params.limit));
  if (params?.level) query.append("level", params.level);
  if (params?.search) query.append("search", params.search);
  if (params?.since_minutes) query.append("since_minutes", String(params.since_minutes));
  const response = await client.get<LogsResponse>(`/admin/monitoring/logs?${query.toString()}`, {
    headers: authHeaders(token)
  });
  return response.data;
}

export async function fetchHealthCheck(token?: string | null): Promise<Record<string, unknown>> {
  const response = await client.get("/health/ready", { headers: authHeaders(token) });
  return response.data;
}

/**
 * Stream chat via SSE. Returns an AbortController to cancel the stream.
 */
export function chatStream(
  question: string,
  tenantId: string,
  token: string | null,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): AbortController {
  const controller = new AbortController();
  fetch(`${apiBase}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      "X-Tenant-ID": tenantId,
    } as Record<string, string>,
    body: JSON.stringify({ question }),
    signal: controller.signal,
  }).then(async (res) => {
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop()!;
      for (const block of blocks) {
        const eventMatch = block.match(/^event: (.+)$/m);
        const dataMatch = block.match(/^data: (.+)$/m);
        if (eventMatch && dataMatch) {
          onEvent(eventMatch[1], JSON.parse(dataMatch[1]));
        }
      }
    }
  }).catch((err) => {
    if (err.name !== "AbortError") {
      console.error("SSE stream error:", err);
    }
  });
  return controller;
}
