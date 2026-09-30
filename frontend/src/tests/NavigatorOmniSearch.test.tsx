import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NavigatorOmniSearch } from '../components/navigator/NavigatorOmniSearch';
import type { OmniSearchResultItem } from '../components/navigator/types';

describe('NavigatorOmniSearch Component', () => {
  const mockMatches: OmniSearchResultItem[] = [
    {
      id: 'sym_1',
      type: 'symbol',
      symbol_id: 10,
      name: 'api_read_file',
      kind: 'function',
      filepath: 'app/api/routers/files.py',
      repo: 'test-repo',
      start_line: 22,
      end_line: 49,
      score: 0.99,
      score_label: '99% AST exact match',
      preview: 'async def api_read_file(path: str)...',
    },
    {
      id: 'file_1',
      type: 'file',
      name: 'files.py',
      kind: 'file',
      filepath: 'app/api/routers/files.py',
      repo: 'test-repo',
      start_line: 1,
      end_line: 83,
      score: 0.92,
      score_label: '92% Filename match',
      preview: 'app/api/routers/files.py',
    },
  ];

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders omni-search input with placeholder', () => {
    render(<NavigatorOmniSearch repo="test-repo" onSelectResult={vi.fn()} />);
    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);
    expect(input).toBeInTheDocument();
  });

  it('fetches matches when user types and displays floating overlay', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        query: 'api_read',
        repo: 'test-repo',
        total_matches: 2,
        matches: mockMatches,
      }),
    } as Response);

    const onSelect = vi.fn();
    render(<NavigatorOmniSearch repo="test-repo" onSelectResult={onSelect} />);

    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);
    fireEvent.change(input, { target: { value: 'api_read' } });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });

    // Check overlay items rendered
    const symbolBadge = await screen.findByText('SYMBOL');
    expect(symbolBadge).toBeInTheDocument();
    expect(screen.getByText('api_read_file')).toBeInTheDocument();
    expect(screen.getByText('99% AST exact match')).toBeInTheDocument();

    // Click result triggers onSelectResult
    fireEvent.click(screen.getByText('api_read_file'));
    expect(onSelect).toHaveBeenCalledWith(mockMatches[0]);
  });

  it('navigates with keyboard and selects on Enter', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        query: 'api_read',
        repo: 'test-repo',
        total_matches: 2,
        matches: mockMatches,
      }),
    } as Response);

    const onSelect = vi.fn();
    render(<NavigatorOmniSearch repo="test-repo" onSelectResult={onSelect} />);

    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);
    fireEvent.change(input, { target: { value: 'api_read' } });

    await screen.findByText('api_read_file');

    // ArrowDown to first match, then Enter
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onSelect).toHaveBeenCalledWith(mockMatches[0]);
  });

  it('closes dropdown on Escape key', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        query: 'api_read',
        repo: 'test-repo',
        total_matches: 2,
        matches: mockMatches,
      }),
    } as Response);

    render(<NavigatorOmniSearch repo="test-repo" onSelectResult={vi.fn()} />);

    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);
    fireEvent.change(input, { target: { value: 'api_read' } });

    await screen.findByText('api_read_file');
    expect(screen.getByTestId('nav-omni-dropdown')).toBeInTheDocument();

    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByTestId('nav-omni-dropdown')).not.toBeInTheDocument();
  });
});
