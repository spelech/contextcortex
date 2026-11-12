import { vi } from 'vitest';

export const mockTopologyRepos = [
  { id: 1, name: 'repo-core', url: 'https://github.com/org/repo-core.git', branch: 'main', status: 'synced' },
  { id: 2, name: 'repo-web', url: 'https://github.com/org/repo-web.git', branch: 'main', status: 'synced' },
];

export const mockTopologyPayload = {
  nodes: [
    { id: 'file:repo-core:app/main.py', name: 'main.py', type: 'file', repo: 'repo-core', filepath: 'app/main.py' },
    { id: 'file:repo-core:app/utils.py', name: 'utils.py', type: 'file', repo: 'repo-core', filepath: 'app/utils.py' },
    { id: 'symbol:1', name: 'handle_request', type: 'function', repo: 'repo-core', filepath: 'app/main.py', start_line: 10, end_line: 25 },
    { id: 'route:1', name: 'GET /api/v1/status', type: 'route', repo: 'repo-core', filepath: 'app/main.py', method: 'GET', path_pattern: '/api/v1/status' },
  ],
  edges: [
    { source: 'file:repo-core:app/main.py', target: 'file:repo-core:app/utils.py', type: 'IMPORTS' },
    { source: 'file:repo-core:app/main.py', target: 'symbol:1', type: 'DEFINES' },
    { source: 'route:1', target: 'symbol:1', type: 'HANDLES' },
  ],
  stats: { node_count: 4, edge_count: 3 },
};

export const mockTopologyNodeDetails = {
  id: 'symbol:1',
  name: 'handle_request',
  type: 'function',
  repo: 'repo-core',
  filepath: 'app/main.py',
  start_line: 10,
  end_line: 25,
  signature: 'def handle_request(req):',
  code_preview: 'def handle_request(req):\n    return {"status": "ok"}',
  permalink: 'https://github.com/org/repo-core/blob/c0ffee1/app/main.py#L10-L25',
  incoming: [
    { id: 'route:1', name: 'GET /api/v1/status', type: 'route', edge_type: 'HANDLES', line_number: 10 },
  ],
  outgoing: [
    { id: 'symbol:2', name: 'format_response', type: 'function', edge_type: 'CALLS', line_number: 18 },
  ],
  metadata: { kind: 'function', language: 'python' },
};

export interface CanvasTestHarness {
  cleanup: () => void;
}

export function installTopologyCanvasAndFetchMocks(): CanvasTestHarness {
  vi.clearAllMocks();
  localStorage.clear();

  const mockCtx: any = {
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    arc: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    fillText: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    scale: vi.fn(),
    setLineDash: vi.fn(),
    measureText: vi.fn(() => ({ width: 50 })),
    canvas: { width: 1000, height: 640 },
  };

  const originalGetContext = HTMLCanvasElement.prototype.getContext;
  const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
  const originalResizeObserver = window.ResizeObserver;

  HTMLCanvasElement.prototype.getContext = vi.fn(function (this: HTMLCanvasElement, contextId: string) {
    if (contextId === '2d') {
      mockCtx.canvas = this;
      return mockCtx;
    }
    return null;
  }) as any;

  HTMLCanvasElement.prototype.toDataURL = vi.fn(() => 'data:image/png;base64,mockpngdata');

  window.ResizeObserver = class {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  } as any;

  (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
    if (url.includes('/admin/api/repos')) {
      return Promise.resolve({
        ok: true,
        json: async () => mockTopologyRepos,
      } as Response);
    }
    if (url.includes('/admin/api/graph/topology')) {
      return Promise.resolve({
        ok: true,
        json: async () => mockTopologyPayload,
      } as Response);
    }
    if (url.includes('/admin/api/graph/node-details')) {
      return Promise.resolve({
        ok: true,
        json: async () => mockTopologyNodeDetails,
      } as Response);
    }
    return Promise.resolve({
      ok: true,
      json: async () => ({}),
    } as Response);
  });

  return {
    cleanup: () => {
      HTMLCanvasElement.prototype.getContext = originalGetContext;
      HTMLCanvasElement.prototype.toDataURL = originalToDataURL;
      window.ResizeObserver = originalResizeObserver;
    },
  };
}
