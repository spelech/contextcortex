export interface LanguageBadgeDescriptor {
  label: string;
  shortCode: string;
  badgeClass: string;
}

const LANGUAGE_DESCRIPTORS: Record<string, LanguageBadgeDescriptor> = {
  python: { label: 'Python', shortCode: 'PY', badgeClass: 'lang-py' },
  py: { label: 'Python', shortCode: 'PY', badgeClass: 'lang-py' },
  typescript: { label: 'TypeScript', shortCode: 'TS', badgeClass: 'lang-ts' },
  ts: { label: 'TypeScript', shortCode: 'TS', badgeClass: 'lang-ts' },
  tsx: { label: 'TSX', shortCode: 'TSX', badgeClass: 'lang-ts' },
  javascript: { label: 'JavaScript', shortCode: 'JS', badgeClass: 'lang-js' },
  js: { label: 'JavaScript', shortCode: 'JS', badgeClass: 'lang-js' },
  jsx: { label: 'JSX', shortCode: 'JSX', badgeClass: 'lang-js' },
  c_sharp: { label: 'C#', shortCode: 'C#', badgeClass: 'lang-cs' },
  csharp: { label: 'C#', shortCode: 'C#', badgeClass: 'lang-cs' },
  cs: { label: 'C#', shortCode: 'C#', badgeClass: 'lang-cs' },
  cobol: { label: 'COBOL', shortCode: 'COB', badgeClass: 'lang-cobol' },
  cbl: { label: 'COBOL', shortCode: 'COB', badgeClass: 'lang-cobol' },
  cob: { label: 'COBOL', shortCode: 'COB', badgeClass: 'lang-cobol' },
  cpy: { label: 'COBOL', shortCode: 'CPY', badgeClass: 'lang-cobol' },
  go: { label: 'Go', shortCode: 'GO', badgeClass: 'lang-go' },
  golang: { label: 'Go', shortCode: 'GO', badgeClass: 'lang-go' },
  rust: { label: 'Rust', shortCode: 'RS', badgeClass: 'lang-rs' },
  rs: { label: 'Rust', shortCode: 'RS', badgeClass: 'lang-rs' },
  java: { label: 'Java', shortCode: 'JV', badgeClass: 'lang-java' },
  cpp: { label: 'C++', shortCode: 'C++', badgeClass: 'lang-cpp' },
  c: { label: 'C', shortCode: 'C', badgeClass: 'lang-cpp' },
  sql: { label: 'SQL', shortCode: 'SQL', badgeClass: 'lang-sql' },
  markdown: { label: 'Markdown', shortCode: 'MD', badgeClass: 'lang-md' },
  md: { label: 'Markdown', shortCode: 'MD', badgeClass: 'lang-md' },
  json: { label: 'JSON', shortCode: '{}', badgeClass: 'lang-json' },
  yaml: { label: 'YAML', shortCode: 'YML', badgeClass: 'lang-yaml' },
  yml: { label: 'YAML', shortCode: 'YML', badgeClass: 'lang-yaml' },
  pdf: { label: 'PDF', shortCode: 'PDF', badgeClass: 'lang-doc' },
};

export function resolveLanguageDescriptor(
  language?: string | null,
  filepath?: string | null
): LanguageBadgeDescriptor | null {
  const normLang = (language || '').trim().toLowerCase();
  const ext = (filepath || '').split('.').pop()?.toLowerCase() || '';

  if (ext === 'tsx') return LANGUAGE_DESCRIPTORS.tsx;
  if (ext === 'jsx') return LANGUAGE_DESCRIPTORS.jsx;
  if (ext === 'cpy') return LANGUAGE_DESCRIPTORS.cpy;
  if (ext === 'cbl' || ext === 'cob') return LANGUAGE_DESCRIPTORS.cobol;
  if (ext === 'cs') return LANGUAGE_DESCRIPTORS.c_sharp;

  if (normLang && LANGUAGE_DESCRIPTORS[normLang]) {
    return LANGUAGE_DESCRIPTORS[normLang];
  }
  if (ext && LANGUAGE_DESCRIPTORS[ext]) {
    return LANGUAGE_DESCRIPTORS[ext];
  }
  return null;
}

export function formatLanguageLabel(
  language?: string | null,
  filepath?: string | null
): string {
  const desc = resolveLanguageDescriptor(language, filepath);
  if (desc) return desc.label;
  if (language && language.trim()) return language.trim();
  return 'text';
}

const SYMBOL_KIND_LABELS: Record<string, string> = {
  class: 'class',
  class_declaration: 'class',
  interface: 'interface',
  interface_declaration: 'interface',
  record: 'record',
  record_declaration: 'record',
  record_definition: 'record',
  program: 'program',
  program_definition: 'program',
  struct: 'struct',
  struct_declaration: 'struct',
  enum: 'enum',
  enum_declaration: 'enum',
  type: 'type',
  type_alias_declaration: 'type',
  function: 'function',
  function_declaration: 'function',
  'async function': 'async function',
  method: 'method',
  method_definition: 'method',
  method_declaration: 'method',
  constructor: 'constructor',
  constructor_declaration: 'constructor',
  section: 'section',
  paragraph: 'paragraph',
  variable: 'variable',
  constant: 'constant',
  property: 'property',
  property_declaration: 'property',
};

const CLASS_CATEGORY_KINDS = new Set([
  'class',
  'class_declaration',
  'interface',
  'interface_declaration',
  'record',
  'record_declaration',
  'record_definition',
  'program',
  'program_definition',
  'struct',
  'struct_declaration',
  'enum',
  'enum_declaration',
  'type',
  'type_alias_declaration',
]);

const FUNCTION_CATEGORY_KINDS = new Set([
  'function',
  'function_declaration',
  'async function',
  'method',
  'method_definition',
  'method_declaration',
  'constructor',
  'constructor_declaration',
  'section',
  'paragraph',
]);

export function formatSymbolKind(kind?: string | null): string {
  const raw = (kind || '').trim();
  if (!raw) return 'symbol';
  const norm = raw.toLowerCase();
  if (SYMBOL_KIND_LABELS[norm]) return SYMBOL_KIND_LABELS[norm];
  return raw.replace(/_/g, ' ');
}

export function classifyOutlineSymbolCategory(
  kind?: string | null
): 'class' | 'function' | 'other' {
  const norm = (kind || '').trim().toLowerCase();
  if (CLASS_CATEGORY_KINDS.has(norm)) return 'class';
  if (FUNCTION_CATEGORY_KINDS.has(norm)) return 'function';
  return 'other';
}

export function getSymbolKindBadgeClass(kind?: string | null): string {
  const norm = (kind || '').trim().toLowerCase();
  if (
    norm === 'class' ||
    norm === 'class_declaration' ||
    norm === 'record' ||
    norm === 'record_declaration' ||
    norm === 'record_definition' ||
    norm === 'program' ||
    norm === 'program_definition'
  ) {
    return 'kind-class';
  }
  if (
    norm === 'interface' ||
    norm === 'interface_declaration' ||
    norm === 'type' ||
    norm === 'type_alias_declaration' ||
    norm === 'struct' ||
    norm === 'struct_declaration' ||
    norm === 'enum' ||
    norm === 'enum_declaration'
  ) {
    return 'kind-type';
  }
  if (FUNCTION_CATEGORY_KINDS.has(norm)) {
    return 'kind-function';
  }
  if (norm === 'variable' || norm === 'constant' || norm === 'property' || norm === 'property_declaration') {
    return 'kind-var';
  }
  return 'kind-default';
}

const BUNDLE_SEGMENTS = [
  '/www/assets/',
  'www/assets/',
  '/wwwroot/_framework/',
  'wwwroot/_framework/',
  '/wwwroot/assets/',
  'wwwroot/assets/',
  '/dist/assets/',
  'dist/assets/',
  '/build/static/',
  'build/static/',
  '/node_modules/',
  'node_modules/',
];

const BUNDLE_SUFFIXES = [
  '.min.js',
  '.min.mjs',
  '.min.css',
  '.bundle.js',
  '.chunk.js',
  '.wasm',
];

export function isCompiledBundlePath(filepath?: string | null): boolean {
  if (!filepath) return false;
  const norm = filepath.replace(/\\/g, '/').trim().toLowerCase();
  if (BUNDLE_SEGMENTS.some((seg) => norm.includes(seg) || norm.startsWith(seg))) {
    return true;
  }
  return BUNDLE_SUFFIXES.some((suffix) => norm.endsWith(suffix));
}
