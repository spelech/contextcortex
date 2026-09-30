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

  it('displays empty state when query returns no matches', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        query: 'unknown_query',
        repo: 'test-repo',
        total_matches: 0,
        matches: [],
      }),
    } as Response);

    render(<NavigatorOmniSearch repo="test-repo" onSelectResult={vi.fn()} />);

    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);
    fireEvent.change(input, { target: { value: 'unknown_query' } });

    const emptyMsg = await screen.findByText(/no matching files, symbols, or code found/i);
    expect(emptyMsg).toBeInTheDocument();
  });

  it('handles fetch error gracefully without crashing', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Network failure'));

    render(<NavigatorOmniSearch repo="test-repo" onSelectResult={vi.fn()} />);

    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);
    fireEvent.change(input, { target: { value: 'api_read' } });

    // Wait debounce duration
    await new Promise((r) => setTimeout(r, 200));

    expect(screen.queryByTestId('nav-omni-dropdown')).not.toBeInTheDocument();
    errorSpy.mockRestore();
  });

  it('closes dropdown when clicking outside the container', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        query: 'api_read',
        repo: 'test-repo',
        total_matches: 2,
        matches: mockMatches,
      }),
    } as Response);

    render(
      <div>
        <div data-testid="outside-area">Outside</div>
        <NavigatorOmniSearch repo="test-repo" onSelectResult={vi.fn()} />
      </div>
    );

    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);
    fireEvent.change(input, { target: { value: 'api_read' } });

    await screen.findByText('api_read_file');
    expect(screen.getByTestId('nav-omni-dropdown')).toBeInTheDocument();

    // Fire mousedown on outside element
    fireEvent.mouseDown(screen.getByTestId('outside-area'));
    expect(screen.queryByTestId('nav-omni-dropdown')).not.toBeInTheDocument();
  });

  it('supports ArrowUp navigation within bounds', async () => {
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

    // ArrowDown to 0 (api_read_file), ArrowDown to 1 (files.py), ArrowUp back to 0 (api_read_file), Enter
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onSelect).toHaveBeenCalledWith(mockMatches[0]);
  });

  it('renders container prefix and highlights query match in symbol and path', async () => {
    const symbolWithContainer: OmniSearchResultItem = {
      id: 'sym_nested',
      type: 'symbol',
      symbol_id: 15,
      name: 'GetAllProviders',
      full_symbol: 'ProvidersController.GetAllProviders',
      kind: 'method_declaration',
      filepath: 'mcp-router-code://Components/Providers/ProvidersController.cs',
      repo: 'test-repo',
      start_line: 25,
      end_line: 60,
      score: 0.95,
      score_label: '95% Prefix match',
      preview: 'public async Task<IActionResult> GetAllProviders()',
    };

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        query: 'Providers',
        repo: 'test-repo',
        total_matches: 1,
        matches: [symbolWithContainer],
      }),
    } as Response);

    render(<NavigatorOmniSearch repo="test-repo" onSelectResult={vi.fn()} />);

    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);
    fireEvent.change(input, { target: { value: 'Providers' } });

    await screen.findByText('GetAllProviders');

    // Container prefix should be displayed
    expect(screen.getByText('ProvidersController.')).toBeInTheDocument();

    // Kind should be cleaned from method_declaration to method
    expect(screen.getByText('method')).toBeInTheDocument();

    // Path should be cleaned of protocol scheme
    expect(screen.getByText('Components/Providers/ProvidersController.cs')).toBeInTheDocument();

    // Query match marks should exist
    const marks = document.querySelectorAll('mark.nav-omni-match');
    expect(marks.length).toBeGreaterThan(0);
  });

  it('focuses search input when pressing Ctrl+K', () => {
    render(<NavigatorOmniSearch repo="test-repo" onSelectResult={vi.fn()} />);
    const input = screen.getByPlaceholderText(/search files, symbols, routes, or code text/i);

    expect(document.activeElement).not.toBe(input);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(document.activeElement).toBe(input);
  });
});

