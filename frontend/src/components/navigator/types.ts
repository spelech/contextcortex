export type DensityMode = 'compact' | 'balanced' | 'spacious';

export type OutlineCategory = 'all' | 'routes' | 'classes' | 'functions';

export interface RouteMeta {
  id?: number;
  framework?: string;
  http_method: string;
  path_pattern: string;
  handler_symbol?: string;
  start_line?: number;
  end_line?: number;
}

export interface NavigatorTreeNode {
  id: string;
  name: string;
  is_dir: boolean;
  path: string;
  language?: string | null;
  symbol_count: number;
  route_count: number;
  children?: NavigatorTreeNode[] | null;
}

export interface NavigatorTreeResponse {
  repo: string;
  total_files: number;
  total_symbols: number;
  tree: NavigatorTreeNode[];
}

export interface SymbolOutlineItem {
  id: number;
  name: string;
  full_symbol?: string;
  kind: string;
  start_line: number;
  end_line: number;
  signature?: string | null;
  language?: string | null;
  route?: RouteMeta | null;
}

export interface FileOutline {
  repo: string;
  filepath: string;
  language?: string | null;
  symbols: SymbolOutlineItem[];
}

export interface SymbolCaller {
  id?: number;
  source_symbol_id?: number | null;
  source_filepath?: string;
  source_symbol?: string;
  target_symbol?: string;
  relationship_type?: string;
  line_number?: number | null;
}

export interface SymbolCallee {
  id?: number;
  target_symbol: string;
  target_filepath?: string;
  relationship_type?: string;
  line_number?: number | null;
}

export interface SymbolImport {
  id?: number;
  target_symbol: string;
  relationship_type?: string;
  line_number?: number | null;
}

export interface SymbolDetail {
  id: number;
  name: string;
  full_symbol?: string;
  kind: string;
  filepath: string;
  start_line: number;
  end_line: number;
  signature?: string | null;
  docstring?: string | null;
  language?: string | null;
  repo?: string;
}

export interface SymbolImpact {
  symbol: SymbolDetail;
  route?: RouteMeta | null;
  callers: SymbolCaller[];
  callees: SymbolCallee[];
  imports: SymbolImport[];
}

export interface RepoOption {
  id?: number;
  name: string;
}
