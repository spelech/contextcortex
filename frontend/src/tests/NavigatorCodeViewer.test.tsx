import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NavigatorCodeViewer } from '../components/navigator/NavigatorCodeViewer';
import type { SymbolImpact } from '../components/navigator/types';

describe('NavigatorCodeViewer Component', () => {
  const sampleCode = `import os\n\ndef hello():\n    return "world"\n\ndef goodbye():\n    pass`;

  const mockImpact: SymbolImpact = {
    symbol: {
      id: 1,
      name: 'hello',
      kind: 'function',
      filepath: 'test.py',
      start_line: 3,
      end_line: 4,
      repo: 'test-repo',
    },
    route: null,
    callers: [
      {
        source_symbol: 'main_caller',
        source_filepath: 'app/main.py',
        line_number: 12,
        call_count: 1,
      },
    ],
    callees: [],
    imports: [],
  };

  beforeEach(() => {
    // Mock scrollIntoView
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it('renders line numbers and code lines', () => {
    render(
      <NavigatorCodeViewer
        filepath="test.py"
        content={sampleCode}
        totalLines={6}
        sizeBytes={120}
      />
    );

    expect(screen.getByText('test.py')).toBeInTheDocument();
    expect(screen.getByText('6 lines')).toBeInTheDocument();
    // Check line numbers 1 and 3 are present
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText(/def hello\(\):/)).toBeInTheDocument();
  });

  it('highlights target line range and calls scrollIntoView', () => {
    render(
      <NavigatorCodeViewer
        filepath="test.py"
        content={sampleCode}
        totalLines={6}
        targetStartLine={3}
        targetEndLine={4}
      />
    );

    const targetLine = screen.getByTestId('code-line-3');
    expect(targetLine).toHaveClass('nav-code-line-target');
    expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it('toggles callers and impact drawer', () => {
    const onSelectCaller = vi.fn();
    render(
      <NavigatorCodeViewer
        filepath="test.py"
        content={sampleCode}
        totalLines={6}
        impact={mockImpact}
        onSelectCaller={onSelectCaller}
      />
    );

    const toggleBtn = screen.getByRole('button', { name: /callers & impact/i });
    expect(toggleBtn).toBeInTheDocument();

    // Click toggle to open drawer
    fireEvent.click(toggleBtn);
    expect(screen.getByText('main_caller')).toBeInTheDocument();

    // Click caller chip
    fireEvent.click(screen.getByText('main_caller'));
    expect(onSelectCaller).toHaveBeenCalledWith('app/main.py', 'main_caller', undefined);
  });
});
