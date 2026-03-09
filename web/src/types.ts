export type TokenResponse = {
  access_token: string;
  token_type: string;
  role: string;
  user_id: string;
  default_tenant_id?: string | null;
};

export type IngestSubmitResponse = {
  job_id: string;
  status: string;
};

export type IngestJobResponse = {
  job_id: string;
  tenant_id: string;
  filename: string;
  status: string;
  chunks_indexed: number;
  document_id?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type RetrievedChunk = {
  text: string;
  score: number;
  source?: string | null;
  page_numbers?: number[] | null;
};

export type DocumentInfo = {
  document_id: string;
  filename: string;
  chunk_count: number;
  created_at: string;
};

export type DocumentDetail = {
  document_id: string;
  tenant_id: string;
  filename: string;
  mime_type: string;
  file_size: number;
  page_count: number;
  chunk_count: number;
  sensitivity: "normal" | "sensitive" | "restricted";
  status: "active" | "archived" | "deleted";
  approval_override: "always" | "never" | null;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type DocumentListResponse = {
  items: DocumentDetail[];
  total: number;
};

export type TenantPolicy = {
  tenant_id: string;
  approval_mode: "all" | "sensitive" | "none";
  updated_at: string | null;
  updated_by: string | null;
};

export type ChatResponse = {
  status: "pending_approval" | "completed";
  answer: string;
  retrieved: RetrievedChunk[];
  approval_id?: string | null;
};

export type AuditRecord = {
  id: number;
  timestamp: string;
  tenant_id: string;
  user: string;
  action: string;
  input_text: string;
  output_text: string;
  metadata: string;
};

export type ApprovalResponse = {
  approval_id: string;
  user_id: string;
  tenant_id: string;
  status: string;
  question: string;
  draft_answer: string;
  final_answer?: string | null;
  created_at: string;
  decided_at?: string | null;
  decision_by?: string | null;
  decision_note?: string | null;
};

export type Tenant = {
  tenant_id: string;
  name: string;
  created_at: string;
};

export type UserAccount = {
  user_id: string;
  username: string;
  role: string;
  default_tenant_id?: string | null;
  tenant_ids: string[];
  created_at: string;
};

export type MetricsSummary = {
  http: {
    total_requests: number;
    error_count: number;
    error_rate: number;
    avg_latency: number;
    by_status: Record<string, number>;
  };
  llm: {
    call_count: number;
    avg_duration: number;
    error_count: number;
    tokens_generated: number;
    by_provider: Record<string, { count: number; avg: number }>;
  };
  rag: {
    query_count: number;
    avg_duration: number;
    by_status: Record<string, number>;
  };
  retrieval: {
    search_count: number;
    avg_duration: number;
    by_type: Record<string, { count: number; avg: number }>;
  };
  embedding: {
    call_count: number;
    avg_duration: number;
    texts_processed: number;
  };
  ingestion: {
    documents_total: number;
    success_count: number;
    error_count: number;
    avg_duration: number;
    chunks_total: number;
    queue_depth: number;
    by_type: Record<string, number>;
  };
  policy: {
    total: number;
    blocked: number;
    passed: number;
    by_result: Record<string, number>;
  };
  health: Record<string, number>;
};

export type LogEntry = {
  timestamp: number;
  level: string;
  logger: string;
  message: string;
  request_id: string;
  extra: Record<string, string>;
};

export type LogsResponse = {
  entries: LogEntry[];
  counts: Record<string, number>;
  total_buffered: number;
};
