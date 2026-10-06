export type UserRole = 'USER' | 'ADMIN';

export interface CurrentUser {
  id: string;
  email: string;
  role: UserRole;
}

export interface NodeInfo {
  id: string;
  base_url: string;
  status: string;
  last_heartbeat?: string | null;
  storage_used_bytes: number;
  chunk_count: number;
  simulated_down: boolean;
}

export interface FileRow {
  id: string;
  name: string;
  content_type?: string | null;
  created_at: string;
  latest_version: number | null;
  size_bytes: number;
}

export interface ReplicaInfo {
  node_id: string;
  state: string;
}

export interface ChunkInfo {
  index: number;
  hash: string;
  size_bytes: number;
  replicas: ReplicaInfo[];
}

export interface FileVersionInfo {
  id: string;
  version_number: number;
  size_bytes: number;
  file_sha256: string;
  created_at: string;
  chunks: ChunkInfo[];
}

export interface FileDetail {
  id: string;
  name: string;
  content_type?: string | null;
  versions: FileVersionInfo[];
}

export interface DashboardActivity {
  type: string;
  message: string;
  created_at: string;
}

export interface Dashboard {
  logical_storage_bytes: number;
  physical_storage_bytes: number;
  unique_chunk_bytes: number;
  dedup_savings_bytes: number;
  file_count: number;
  snapshot_count: number;
  degraded_chunks: number;
  active_repairs: number;
  healthy_nodes: number;
  node_count: number;
  activity: DashboardActivity[];
  metrics: Record<string, string>;
}

export interface SnapshotInfo {
  id: string;
  name: string;
  created_at: string;
  entry_count: number;
}

export interface RepairInfo {
  id: string;
  chunk_hash: string;
  source: string | null;
  target: string | null;
  state: string;
  duration_ms: number | null;
  created_at: string;
}

export interface DataHealthCounts {
  HEALTHY: number;
  DEGRADED: number;
  REPAIRING: number;
  UNRECOVERABLE: number;
}

export interface DataHealthSummary {
  objects: DataHealthCounts;
  chunks: DataHealthCounts;
  object_count: number;
  chunk_count: number;
}

export interface IntegrityState {
  replica_states: Record<string, number>;
  data_health: DataHealthSummary;
  repairs: RepairInfo[];
}

export interface AuditEventInfo {
  id: string;
  event_type: string;
  message: string;
  actor_id: string | null;
  correlation_id: string | null;
  created_at: string;
}

export interface ChunkDescriptor {
  index: number;
  hash: string;
  size: number;
}

export interface UploadSessionCreateResponse {
  session_id: string;
  missing_chunks: number[];
  chunk_size: number;
  status: 'ACTIVE' | 'FINALIZED' | 'ABORTED';
  created_at: string;
}

export interface UploadSessionStatusResponse {
  session_id: string;
  status: 'ACTIVE' | 'FINALIZED' | 'ABORTED';
  file_name: string;
  expected_size: number;
  chunk_size: number;
  created_at: string;
  missing_chunks: number[];
  received_chunks: number[];
}

export interface FinalizeUploadResponse {
  file_version_id: string;
  version_number: number;
  file_sha256: string;
}

export interface VersionRestoreResponse extends FinalizeUploadResponse {
  restored_from_version: number;
}
