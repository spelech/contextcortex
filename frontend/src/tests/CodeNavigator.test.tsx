import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CodeNavigator from '../CodeNavigator';

const mockRepos = [
  { id: 1, name: 'repo-core' },
  { id: 2, name: 'repo-web' },
];

const mockTreeData = {
  repo: '__all__',
  total_files: 2,
  total_symbols: 5,
  tree: [
    {
      id: 'file:app/main.py',
      name: 'main.py',
      is_dir: false,
      path: 'app/main.py',
      language: 'python',
      symbol_count: 3,
      route_count: 1,
    },
    {
      id: 'file:tests/test_main.py',
      name: 'test_main.py',
      is_dir: false,
      path: 'tests/test_main.py',
      language: 'python',
      symbol_count: 2,
      route_count: 0,
    },
  ],
};

const mockOutlineMain = {
  repo: '__all__',
  filepath: 'app/main.py',
  language: 'python',
  symbols: [
    {
      id: 101,
      name: 'handle_request',
      full_symbol: 'app.main.handle_request',
      kind: 'function',
      start_line: 10,
      end_line: 25,
      signature: 'def handle_request(req):',
      route: {
        http_method: 'GET',
        path_pattern: '/api/status',
        framework: 'FastAPI',
      },
    },
    {
      id: 102,
      name: 'AppConfig',
      full_symbol: 'app.main.AppConfig',
      kind: 'class',
      start_line: 30,
      end_line: 50,
      signature: 'class AppConfig:',
    },
  ],
};

const mockOutlineTest = {
  repo: '__all__',
  filepath: 'tests/test_main.py',
  language: 'python',
  symbols: [
    {
      id: 201,
      name: 'test_handle_request',
      full_symbol: 'tests.test_main.test_handle_request',
      kind: 'function',
      start_line: 5,
      end_line: 15,
      signature: 'def test_handle_request():',
    },
  ],
};

const mockImpactHandleRequest = {
  symbol: {
    id: 101,
    name: 'handle_request',
    full_symbol: 'app.main.handle_request',
    kind: 'function',
    filepath: 'app/main.py',
    start_line: 10,
    end_line: 25,
    signature: 'def handle_request(req):',
    docstring: 'Handles incoming requests.',
    language: 'python',
  },
  route: {
    http_method: 'GET',
    path_pattern: '/api/status',
    framework: 'FastAPI',
  },
  callers: [
    {
      id: 1,
      source_symbol_id: 201,
      source_symbol: 'test_handle_request',
      source_filepath: 'tests/test_main.py',
      relationship_type: 'CALLS',
      line_number: 12,
    },
  ],
  callees: [],
  imports: [],
};

const mockImpactTestHandleRequest = {
  symbol: {
    id: 201,
    name: 'test_handle_request',
    full_symbol: 'tests.test_main.test_handle_request',
    kind: 'function',
    filepath: 'tests/test_main.py',
    start_line: 5,
    end_line: 15,
    signature: 'def test_handle_request():',
    docstring: 'Tests handle request function.',
    language: 'python',
  },
  route: null,
  callers: [],
  callees: [
    {
      id: 2,
      target_symbol: 'handle_request',
      target_filepath: 'app/main.py',
      relationship_type: 'CALLS',
      line_number: 12,
    },
  ],
  imports: [],
};

describe('CodeNavigator Container', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/repositories') || url.includes('/admin/api/repos')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockRepos),
        });
      }
      if (url.includes('/admin/api/navigator/tree')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockTreeData),
        });
      }
      if (url.includes('/admin/api/navigator/file-outline')) {
        if (decodeURIComponent(url).includes('tests/test_main.py')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(mockOutlineTest),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockOutlineMain),
        });
      }
      if (url.includes('/admin/api/navigator/symbol-impact')) {
        if (url.includes('symbol_id=201')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(mockImpactTestHandleRequest),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockImpactHandleRequest),
        });
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });
  });

  it('renders toolbar, 3-pane layout, and fetches initial tree data', async () => {
    render(<CodeNavigator />);

    // Check toolbar elements
    await waitFor(() => {
      expect(screen.getByText('main.py')).toBeInTheDocument();
      expect(screen.getByText('test_main.py')).toBeInTheDocument();
    });

    // Check Pane titles / headers
    expect(screen.getByText(/files & modules/i)).toBeInTheDocument();
    expect(screen.getByText(/symbols & routes/i)).toBeInTheDocument();
    expect(screen.getByText(/code intelligence & impact/i)).toBeInTheDocument();
  });

  it('handles density mode switching and persists to localStorage', async () => {
    render(<CodeNavigator />);

    await waitFor(() => {
      expect(screen.getByText('main.py')).toBeInTheDocument();
    });

    const compactBtn = screen.getByRole('button', { name: /compact/i });
    fireEvent.click(compactBtn);

    expect(localStorage.getItem('contextcortex_navigator_density')).toBe('compact');
    expect(screen.getByTestId('code-navigator-container')).toHaveClass('density-compact');

    const spaciousBtn = screen.getByRole('button', { name: /spacious/i });
    fireEvent.click(spaciousBtn);

    expect(localStorage.getItem('contextcortex_navigator_density')).toBe('spacious');
    expect(screen.getByTestId('code-navigator-container')).toHaveClass('density-spacious');
  });

  it('loads file outline on file selection and symbol impact on symbol selection', async () => {
    render(<CodeNavigator />);

    await waitFor(() => {
      expect(screen.getByText('main.py')).toBeInTheDocument();
    });

    // Click main.py
    const mainFile = screen.getByText('main.py');
    fireEvent.click(mainFile);

    // Outline should load symbols
    await waitFor(() => {
      expect(screen.getByTestId('symbol-item-101')).toBeInTheDocument();
      expect(screen.getByText('AppConfig')).toBeInTheDocument();
    });

    // Click handle_request symbol item
    fireEvent.click(screen.getByTestId('symbol-item-101'));

    // Inspector should load symbol impact
    await waitFor(() => {
      expect(screen.getByText(/handles incoming requests/i)).toBeInTheDocument();
      expect(screen.getAllByText('/api/status').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('supports caller click-through navigation jumping to caller file and symbol', async () => {
    render(<CodeNavigator />);

    await waitFor(() => {
      expect(screen.getByText('main.py')).toBeInTheDocument();
    });

    // Select main.py
    fireEvent.click(screen.getByText('main.py'));

    await waitFor(() => {
      expect(screen.getByTestId('symbol-item-101')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('symbol-item-101'));

    await waitFor(() => {
      expect(screen.getByTestId('caller-item-1')).toBeInTheDocument();
    });

    // Click the caller in inspector
    const callerCard = screen.getByTestId('caller-item-1');
    fireEvent.click(callerCard);

    // Should jump to tests/test_main.py, load outline, and load test_handle_request impact
    await waitFor(() => {
      expect(screen.getAllByText('test_main.py').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/tests handle request function/i)).toBeInTheDocument();
    });
  });



  it('handles repo switcher change and re-fetches tree', async () => {
    render(<CodeNavigator />);

    await waitFor(() => {
      expect(screen.getByText('main.py')).toBeInTheDocument();
    });

    const repoSelect = screen.getByRole('combobox', { name: /repository/i });
    fireEvent.change(repoSelect, { target: { value: 'repo-core' } });

    await waitFor(() => {
      expect((globalThis as any).fetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/api/navigator/tree?repo=repo-core')
      );
    });
  });
});
