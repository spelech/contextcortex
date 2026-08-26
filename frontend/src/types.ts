export interface Stats {
  repos_count: number;
  symbols_count: number;
  files_count: number;
  points_count: number;
  last_indexed: string;
  dense_model?: string;
  sparse_model?: string;
  embedding_provider?: 'local' | 'api' | string;
  embedding_threads?: number;
  embedding_batch_size?: number;
  system_cpus?: number;
  system_memory_gb?: number;
  rate_limit?: {
    remaining: number;
    limit: number;
  };
  top_keywords?: string[];
  is_indexing: boolean;
  token_source?: string;
  masked_token?: string;
  providers_auth?: {
    github?: { token_source: string; masked_token: string };
    gitlab?: { token_source: string; masked_token: string };
    gitea?: { token_source: string; masked_token: string };
  };
  vector_store_provider?: 'qdrant' | 'chroma' | string;
  vector_store_mode?: 'embedded' | 'remote' | string;
  vector_store_collection?: string;
}

export interface EmbeddingConfig {
  provider: 'local' | 'api';
  dense_model: string;
  sparse_model: string;
  threads: number;
  batch_size: number;
  litellm_url?: string;
  litellm_api_key?: string;
  system_cpus?: number;
  system_memory_gb?: number;
}

export interface AutoSyncSettings {
  interval_mins: number;
  webhook_url: string;
  has_global_secret: boolean;
}

export interface VectorStoreConfig {
  provider: 'qdrant' | 'chroma';
  mode: 'embedded' | 'remote';
  storage_path?: string | null;
  url?: string | null;
  collection: string;
  healthy?: boolean;
  health_message?: string;
  points_count?: number;
  stats?: {
    points_count?: number;
    vector_dimension?: number;
    error?: string;
    [key: string]: any;
  };
}

export interface Repo {
  id: number;
  name: string;
  url: string;
  branch: string;
  commit_sha?: string;
  provider?: string;
  auth_user?: string;
  status: 'syncing' | 'error' | 'pending' | 'synced';
  last_error?: string;
  file_count?: number;
  last_synced?: string;
  auto_sync?: number | boolean;
  webhook_secret?: string;
}

export type GitRepo = Repo;

export interface GitHostCredential {
  id: number;
  host: string;
  provider: 'github' | 'gitlab' | 'gitea' | 'bitbucket' | 'generic';
  auth_user?: string;
  masked_token: string;
  added_at: string;
}

export interface LocalPath {
  id: number;
  path: string;
  repo: string;
  type: string;
  recursive: boolean;
  category?: string;
  enabled: boolean;
}

export interface BrowseData {
  current_path: string;
  parent_path: string | null;
  directories: { name: string; path: string }[];
  files: { name: string; path: string }[];
}

export interface SearchHit {
  score: number;
  payload: {
    repo: string;
    rel_path: string;
    symbol?: string;
    start_line: number;
    end_line: number;
    github_url?: string;
    content: string;
  };
}

export interface DiagnosticLog {
  timestamp: string;
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG';
  logger: string;
  message: string;
  traceback: string | null;
}

export interface TopologyNode {
  id: string;
  name: string;
  type: 'file' | 'module' | 'class' | 'function' | 'route' | string;
  repo: string;
  filepath?: string;
  language?: string;
  kind?: string;
  start_line?: number;
  end_line?: number;
  signature?: string;
  method?: string;
  path_pattern?: string;
  metadata?: Record<string, any>;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface TopologyEdge {
  source: string;
  target: string;
  type: 'IMPORTS' | 'CALLS' | 'DEFINES' | 'HANDLES' | 'ROUTES_TO' | string;
  label?: string;
  line_number?: number;
  metadata?: Record<string, any>;
}

export interface TopologyStats {
  node_count: number;
  edge_count: number;
}

export interface TopologyGraphData {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  stats: TopologyStats;
}

export interface NeighborDetail {
  id: string;
  name: string;
  type: string;
  edge_type: string;
  filepath?: string;
  line_number?: number;
  permalink?: string;
}

export interface NodeDetails {
  id: string;
  name: string;
  type: string;
  repo: string;
  filepath?: string;
  start_line?: number;
  end_line?: number;
  signature?: string;
  code_preview?: string;
  permalink?: string;
  incoming: NeighborDetail[];
  outgoing: NeighborDetail[];
  metadata?: Record<string, any>;
}


