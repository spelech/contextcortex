import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Marked } from 'marked';
import mermaid from 'mermaid';

interface NavigatorDocReaderProps {
  filepath: string;
  content: string;
  totalLines: number;
  sizeBytes: number;
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
}

// Configured GFM markdown parser with Mermaid code block interception
const markdownParser = new Marked({
  gfm: true,
  breaks: true,
  renderer: {
    code({ text, lang }: { text: string; lang?: string }) {
      if (lang === 'mermaid') {
        return `<div class="mermaid-container"><div class="mermaid">${text}</div></div>\n`;
      }
      return false; // use standard code block rendering
    },
  },
});

/**
 * Normalizes loose or non-standard markdown tables:
 * 1. Automatically inserts missing separator rows (| --- | --- |) after header rows
 * 2. Bridges blank lines between consecutive table rows (common in notes and changelogs)
 * 3. Preserves code blocks (``` and ~~~) without modification
 */
function normalizeMarkdownTables(md: string): string {
  const lines = md.split('\n');
  const result: string[] = [];
  let inCodeBlock = false;
  let inTable = false;
  let tableColCount = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Preserve code blocks verbatim
    if (trimmed.startsWith('```') || trimmed.startsWith('~~~')) {
      inCodeBlock = !inCodeBlock;
      inTable = false;
      result.push(line);
      continue;
    }

    if (inCodeBlock) {
      result.push(line);
      continue;
    }

    const isTableRow = trimmed.startsWith('|') && trimmed.endsWith('|') && trimmed.includes('|');

    if (isTableRow) {
      const colCount = Math.max(1, trimmed.split('|').length - 2);

      if (!inTable) {
        inTable = true;
        tableColCount = colCount;
        result.push(line);

        // Peek next non-empty line
        let nextIdx = i + 1;
        while (nextIdx < lines.length && lines[nextIdx].trim() === '') nextIdx++;

        if (nextIdx < lines.length) {
          const nextTrimmed = lines[nextIdx].trim();
          const isSeparator = /^\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?$/.test(nextTrimmed);
          if (!isSeparator && nextTrimmed.startsWith('|') && nextTrimmed.endsWith('|')) {
            // Missing separator row under header! Auto-insert matching columns
            const separator = '|' + Array(tableColCount).fill(' --- ').join('|') + '|';
            result.push(separator);
          }
        }
      } else {
        result.push(line);
      }
    } else if (trimmed === '' && inTable) {
      // Check if next non-empty line is also a table row (bridging human blank lines in tables)
      let nextIdx = i + 1;
      while (nextIdx < lines.length && lines[nextIdx].trim() === '') nextIdx++;
      if (nextIdx < lines.length && lines[nextIdx].trim().startsWith('|') && lines[nextIdx].trim().endsWith('|')) {
        continue;
      } else {
        inTable = false;
        result.push(line);
      }
    } else {
      inTable = false;
      result.push(line);
    }
  }

  return result.join('\n');
}

export const NavigatorDocReader: React.FC<NavigatorDocReaderProps> = ({
  filepath,
  content,
  totalLines,
  sizeBytes,
  loading = false,
  error = null,
  onRefresh,
}) => {
  const isMarkdown = filepath.toLowerCase().endsWith('.md') || filepath.toLowerCase().endsWith('.markdown');
  const [viewMode, setViewMode] = useState<'rendered' | 'raw'>(isMarkdown ? 'rendered' : 'raw');
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleCopy = async () => {
    if (!content) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(content);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const basename = filepath ? filepath.split('/').pop() || filepath : '';

  // Render HTML via Marked parser with table normalization
  const renderedHtml = useMemo(() => {
    if (!content) return '';
    try {
      const normalized = normalizeMarkdownTables(content);
      return markdownParser.parse(normalized) as string;
    } catch (e) {
      console.error('Failed to parse markdown:', e);
      return `<pre class="doc-code-block"><code>${content}</code></pre>`;
    }
  }, [content]);

  // Render Mermaid diagrams whenever renderedHtml or viewMode updates
  useEffect(() => {
    if (viewMode !== 'rendered' || !containerRef.current) return;

    const mermaidNodes = containerRef.current.querySelectorAll<HTMLElement>('.mermaid');
    if (mermaidNodes.length === 0) return;

    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        securityLevel: 'loose',
        fontFamily: 'monospace, sans-serif',
        themeVariables: {
          darkMode: true,
          background: '#07181b',
          primaryColor: '#0891b2',
          primaryTextColor: '#f8fafc',
          primaryBorderColor: '#15474d',
          lineColor: '#2dd4bf',
          secondaryColor: '#164e63',
          tertiaryColor: '#0d2c2f',
        },
      });

      // Filter unrendered nodes
      const unrendered = Array.from(mermaidNodes).filter((n) => !n.getAttribute('data-processed'));
      if (unrendered.length > 0) {
        mermaid.run({
          nodes: unrendered,
        }).catch((err) => {
          console.warn('Mermaid rendering warning:', err);
        });
      }
    } catch (e) {
      console.warn('Failed to initialize mermaid:', e);
    }
  }, [renderedHtml, viewMode]);

  return (
    <div className="nav-doc-reader" data-testid="nav-doc-reader">
      {/* Header Toolbar */}
      <div className="doc-reader-header">
        <div className="doc-header-meta">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          <span className="doc-filename" title={filepath}>
            {basename}
          </span>
          <span className="doc-badge-chip">{totalLines} lines</span>
          {sizeBytes > 0 && <span className="doc-badge-chip">{formatSize(sizeBytes)}</span>}
        </div>

        <div className="doc-header-actions">
          {isMarkdown && (
            <div className="doc-view-toggle" role="group" aria-label="Document View Mode">
              <button
                type="button"
                className={`toggle-btn ${viewMode === 'rendered' ? 'active' : ''}`}
                onClick={() => setViewMode('rendered')}
                aria-pressed={viewMode === 'rendered'}
              >
                Rendered
              </button>
              <button
                type="button"
                className={`toggle-btn ${viewMode === 'raw' ? 'active' : ''}`}
                onClick={() => setViewMode('raw')}
                aria-pressed={viewMode === 'raw'}
              >
                Raw Source
              </button>
            </div>
          )}

          <button
            type="button"
            className="doc-copy-btn"
            onClick={handleCopy}
            title="Copy document content"
            aria-label="Copy Document Content"
          >
            {copied ? '✓ Copied!' : 'Copy Content'}
          </button>
        </div>
      </div>

      {/* Doc Reader Body */}
      <div className="doc-reader-body">
        {loading ? (
          <div className="doc-reader-loading" data-testid="doc-loading">
            <div className="skeleton-header shimmer"></div>
            <div className="skeleton-block shimmer"></div>
            <div className="skeleton-block shimmer"></div>
          </div>
        ) : error ? (
          <div className="doc-reader-error" role="alert">
            <p>Failed to load file content: {error}</p>
            {onRefresh && (
              <button type="button" className="btn btn-sm btn-primary" onClick={onRefresh}>
                Retry
              </button>
            )}
          </div>
        ) : viewMode === 'rendered' && isMarkdown ? (
          <div
            ref={containerRef}
            className="doc-rendered-content"
            data-testid="doc-rendered-content"
            dangerouslySetInnerHTML={{ __html: renderedHtml }}
          />
        ) : (
          <div className="doc-raw-container" data-testid="doc-raw-content">
            <pre className="doc-raw-pre">
              <table className="doc-lines-table">
                <tbody>
                  {content.split('\n').map((line, idx) => (
                    <tr key={idx} className="doc-line-row">
                      <td className="doc-line-num" data-line-number={idx + 1}>{idx + 1}</td>
                      <td className="doc-line-code"><code>{line || ' '}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </pre>
          </div>
        )}
      </div>
    </div>
  );
};
