import React, { useState } from 'react';

interface NavigatorDocReaderProps {
  filepath: string;
  content: string;
  totalLines: number;
  sizeBytes: number;
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
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

  // Simple safe Markdown parser for formatted preview
  const renderMarkdown = (text: string) => {
    const lines = text.split('\n');
    const elements: React.ReactNode[] = [];
    let inCodeBlock = false;
    let codeBlockLang = '';
    let codeBlockLines: string[] = [];

    lines.forEach((line, index) => {
      // Code block toggle
      if (line.trim().startsWith('```')) {
        if (inCodeBlock) {
          elements.push(
            <pre key={`code-${index}`} className={`doc-code-block ${codeBlockLang}`.trim()}>
              <code>{codeBlockLines.join('\n')}</code>
            </pre>
          );
          codeBlockLines = [];
          inCodeBlock = false;
        } else {
          inCodeBlock = true;
          codeBlockLang = line.trim().slice(3);
        }
        return;
      }

      if (inCodeBlock) {
        codeBlockLines.push(line);
        return;
      }

      // Headings
      if (line.startsWith('# ')) {
        elements.push(<h1 key={`h1-${index}`} className="doc-h1">{line.slice(2)}</h1>);
      } else if (line.startsWith('## ')) {
        elements.push(<h2 key={`h2-${index}`} className="doc-h2">{line.slice(3)}</h2>);
      } else if (line.startsWith('### ')) {
        elements.push(<h3 key={`h3-${index}`} className="doc-h3">{line.slice(4)}</h3>);
      } else if (line.startsWith('#### ')) {
        elements.push(<h4 key={`h4-${index}`} className="doc-h4">{line.slice(5)}</h4>);
      } else if (line.trim() === '---' || line.trim() === '***') {
        elements.push(<hr key={`hr-${index}`} className="doc-divider" />);
      } else if (line.startsWith('> ')) {
        elements.push(<blockquote key={`quote-${index}`} className="doc-quote">{line.slice(2)}</blockquote>);
      } else if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
        elements.push(
          <li key={`li-${index}`} className="doc-list-item">
            {formatInline(line.trim().slice(2))}
          </li>
        );
      } else if (/^\d+\.\s/.test(line.trim())) {
        const itemText = line.trim().replace(/^\d+\.\s/, '');
        elements.push(
          <li key={`oli-${index}`} className="doc-numbered-item">
            {formatInline(itemText)}
          </li>
        );
      } else if (line.trim() === '') {
        elements.push(<div key={`blank-${index}`} className="doc-blank-line" />);
      } else {
        elements.push(<p key={`p-${index}`} className="doc-paragraph">{formatInline(line)}</p>);
      }
    });

    if (inCodeBlock && codeBlockLines.length > 0) {
      elements.push(
        <pre key="code-tail" className="doc-code-block">
          <code>{codeBlockLines.join('\n')}</code>
        </pre>
      );
    }

    return elements;
  };

  // Helper for inline bold, inline code, links
  const formatInline = (text: string): React.ReactNode => {
    // Process inline code `foo`
    const parts = text.split(/(`[^`]+`)/);
    return parts.map((part, i) => {
      if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
        return <code key={i} className="doc-inline-code">{part.slice(1, -1)}</code>;
      }
      // Process bold **text**
      const boldParts = part.split(/(\*\*[^*]+\*\*)/);
      return boldParts.map((bPart, j) => {
        if (bPart.startsWith('**') && bPart.endsWith('**') && bPart.length >= 4) {
          return <strong key={`${i}-${j}`}>{bPart.slice(2, -2)}</strong>;
        }
        return bPart;
      });
    });
  };

  return (
    <div className="nav-doc-reader" data-testid="nav-doc-reader">
      {/* Doc Reader Header */}
      <div className="doc-reader-header">
        <div className="doc-reader-meta">
          <span className="doc-icon">{isMarkdown ? '📝' : '📄'}</span>
          <div className="doc-title-wrapper">
            <h3 className="doc-filename" title={filepath}>{basename}</h3>
            <div className="doc-meta-badges">
              <span className="doc-badge badge-path">{filepath}</span>
              <span className="doc-badge badge-lines">{totalLines} lines</span>
              <span className="doc-badge badge-size">{formatSize(sizeBytes)}</span>
            </div>
          </div>
        </div>

        <div className="doc-reader-actions">
          {isMarkdown && (
            <div className="doc-view-toggle" role="group" aria-label="View Mode">
              <button
                type="button"
                className={`toggle-btn ${viewMode === 'rendered' ? 'active' : ''}`}
                onClick={() => setViewMode('rendered')}
              >
                Rendered
              </button>
              <button
                type="button"
                className={`toggle-btn ${viewMode === 'raw' ? 'active' : ''}`}
                onClick={() => setViewMode('raw')}
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
          <div className="doc-rendered-content" data-testid="doc-rendered-content">
            {renderMarkdown(content)}
          </div>
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
