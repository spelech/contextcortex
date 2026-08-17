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
}

export interface Repo {
  id: number;
  name: string;
  url: string;
  branch: string;
  commit_sha?: string;
  status: 'syncing' | 'error' | 'pending' | 'synced';
  last_error?: string;
  file_count?: number;
  last_synced?: string;
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

