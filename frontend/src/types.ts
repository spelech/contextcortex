export interface Stats {
  repos_count: number;
  symbols_count: number;
  files_count: number;
  points_count: number;
  last_indexed: string;
  dense_model?: string;
  sparse_model?: string;
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
}

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

