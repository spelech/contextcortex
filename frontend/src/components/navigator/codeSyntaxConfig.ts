import Prism from 'prismjs';
import 'prismjs/components/prism-csharp';
import 'prismjs/components/prism-c';
import 'prismjs/components/prism-cpp';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-tsx';
import 'prismjs/components/prism-go';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-docker';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-plsql';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-yaml';
import 'prismjs/components/prism-cobol';

export { Prism };

export const universalIDETheme = {
  plain: {
    color: '#d4d4d4',
    backgroundColor: '#1e1e1e',
  },
  styles: [
    {
      types: ['comment', 'prolog', 'doctype', 'cdata'],
      style: { color: '#6a9955', fontStyle: 'italic' as const },
    },
    {
      types: ['level'],
      style: { color: '#38bdf8', fontWeight: 'bold' as const },
    },
    {
      types: ['keyword', 'builtin-keyword'],
      style: { color: '#569cd6' },
    },
    {
      types: [
        'class-name',
        'return-type',
        'type-list',
        'namespace',
        'base-clause',
        'builtin',
      ],
      style: { color: '#4ec9b0' },
    },
    {
      types: ['interface'],
      style: { color: '#b8d7a3' },
    },
    {
      types: ['function', 'generic-function', 'function-variable', 'generic-method'],
      style: { color: '#dcdcaa' },
    },
    {
      types: ['decorator', 'attribute'],
      style: { color: '#dcdcaa' },
    },
    {
      types: [
        'string',
        'char',
        'attr-value',
        'triple-quoted-string',
        'raw-string',
        'template-string',
        'interpolation-string',
        'string-interpolation',
      ],
      style: { color: '#ce9178' },
    },
    {
      types: ['number', 'boolean'],
      style: { color: '#b5cea8' },
    },
    {
      types: [
        'variable',
        'parameter',
        'named-parameter',
        'property',
        'string-property',
        'attr-name',
        'identifier',
      ],
      style: { color: '#9cdcfe' },
    },
    {
      types: ['constant', 'symbol'],
      style: { color: '#4fc1ff' },
    },
    {
      types: ['macro', 'directive', 'preprocessor', 'preprocessor-directive'],
      style: { color: '#c586c0' },
    },
    {
      types: ['directive-hash'],
      style: { color: '#9b9b9b' },
    },
    {
      types: ['tag'],
      style: { color: '#569cd6' },
    },
    {
      types: ['regex'],
      style: { color: '#d16969' },
    },
    {
      types: ['punctuation', 'operator', 'double-colon'],
      style: { color: '#d4d4d4' },
    },
  ],
};

const PRISM_LANGUAGE_BY_EXT: Record<string, string> = {
  cs: 'csharp',
  csharp: 'csharp',
  c_sharp: 'csharp',
  py: 'python',
  pyw: 'python',
  python: 'python',
  ts: 'typescript',
  typescript: 'typescript',
  tsx: 'tsx',
  js: 'javascript',
  javascript: 'javascript',
  jsx: 'jsx',
  mjs: 'javascript',
  cjs: 'javascript',
  c: 'c',
  h: 'cpp',
  cpp: 'cpp',
  cc: 'cpp',
  cxx: 'cpp',
  hpp: 'cpp',
  hh: 'cpp',
  hxx: 'cpp',
  go: 'go',
  rs: 'rust',
  rust: 'rust',
  json: 'json',
  yml: 'yaml',
  yaml: 'yaml',
  md: 'markdown',
  markdown: 'markdown',
  css: 'css',
  scss: 'css',
  html: 'markup',
  xml: 'markup',
  svg: 'markup',
  sql: 'sql',
  psql: 'sql',
  pls: 'plsql',
  plsql: 'plsql',
  pkb: 'plsql',
  pks: 'plsql',
  ddl: 'sql',
  dml: 'sql',
  cql: 'sql',
  hql: 'sql',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  dockerfile: 'docker',
  cbl: 'cobol',
  cob: 'cobol',
  cpy: 'cobol',
  cobol: 'cobol',
  pco: 'cobol',
};

export function getPrismLanguage(filepath: string): string {
  const clean = filepath.split('?')[0].split('#')[0];
  const ext = (clean.split('.').pop() || '').toLowerCase();
  const candidate = PRISM_LANGUAGE_BY_EXT[ext] || 'plain';
  return (Prism.languages as Record<string, any>)[candidate] ? candidate : 'plain';
}

export function formatCodeSize(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
