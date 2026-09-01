import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NavigatorInspector } from '../components/navigator/NavigatorInspector';
import type { SymbolImpact } from '../components/navigator/types';

const mockImpact: SymbolImpact = {
  symbol: {
    id: 1042,
    name: 'chat_completion_endpoint',
    full_symbol: 'app.api.routers.chat.chat_completion_endpoint',
    kind: 'function',
    filepath: 'app/api/routers/chat.py',
    start_line: 42,
    end_line: 98,
    signature: 'async def chat_completion_endpoint(request: Request, body: ChatCompletionRequest) -> Response',
    docstring: 'OpenAI-compatible chat completion endpoint supporting streaming and routing.',
    language: 'python',
    repo: 'model-context-gateway',
  },
  route: {
    framework: 'FastAPI',
    http_method: 'POST',
    path_pattern: '/v1/chat/completions',
  },
  callers: [
    {
      id: 1,
      source_symbol_id: 512,
      source_symbol: 'test_chat_completions_e2e',
      source_filepath: 'tests/e2e/test_chat.py',
      line_number: 55,
      relationship_type: 'CALLS',
    },
  ],
  callees: [
    {
      id: 2,
      target_symbol: 'LiteLLMGateway.execute_call',
      target_filepath: 'app/services/llm_gateway.py',
      line_number: 120,
      relationship_type: 'CALLS',
    },
  ],
  imports: [
    {
      id: 3,
      target_symbol: 'fastapi.APIRouter',
      relationship_type: 'IMPORTS',
      line_number: 5,
    },
  ],
};

describe('NavigatorInspector Component', () => {
  beforeEach(() => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it('renders empty placeholder when no symbol is selected', () => {
    render(
      <NavigatorInspector
        impact={null}
        onSelectCaller={vi.fn()}
      />
    );

    expect(screen.getByText(/select a symbol from the outline/i)).toBeInTheDocument();
  });

  it('renders symbol metadata and metrics', () => {
    render(
      <NavigatorInspector
        impact={mockImpact}
        onSelectCaller={vi.fn()}
      />
    );

    expect(screen.getByText('chat_completion_endpoint')).toBeInTheDocument();
    expect(screen.getByText('app/api/routers/chat.py')).toBeInTheDocument();
    expect(screen.getByText('L42 - L98')).toBeInTheDocument();

    // Metrics
    expect(screen.getByTestId('metric-callers')).toHaveTextContent('1');
    expect(screen.getByTestId('metric-callees')).toHaveTextContent('1');
    expect(screen.getByTestId('metric-imports')).toHaveTextContent('1');
  });

  it('renders route details card', () => {
    render(
      <NavigatorInspector
        impact={mockImpact}
        onSelectCaller={vi.fn()}
      />
    );

    expect(screen.getByText('POST')).toBeInTheDocument();
    expect(screen.getByText('/v1/chat/completions')).toBeInTheDocument();
    expect(screen.getByText('FastAPI')).toBeInTheDocument();
  });

  it('renders signature code and docstring', () => {
    render(
      <NavigatorInspector
        impact={mockImpact}
        onSelectCaller={vi.fn()}
      />
    );

    expect(screen.getByText(/async def chat_completion_endpoint/i)).toBeInTheDocument();
    expect(screen.getByText(/OpenAI-compatible chat completion endpoint/i)).toBeInTheDocument();
  });

  it('copies permalink to clipboard on button click', async () => {
    render(
      <NavigatorInspector
        impact={mockImpact}
        onSelectCaller={vi.fn()}
      />
    );

    const copyBtn = screen.getByRole('button', { name: /copy permalink/i });
    fireEvent.click(copyBtn);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('app/api/routers/chat.py#L42-L98')
    );
    expect(await screen.findByText(/copied/i)).toBeInTheDocument();
  });

  it('calls onSelectCaller when a caller is clicked for click-through navigation', () => {
    const handleSelectCaller = vi.fn();
    render(
      <NavigatorInspector
        impact={mockImpact}
        onSelectCaller={handleSelectCaller}
      />
    );

    const callerItem = screen.getByTestId('caller-item-1');
    fireEvent.click(callerItem);

    expect(handleSelectCaller).toHaveBeenCalledWith(
      'tests/e2e/test_chat.py',
      'test_chat_completions_e2e',
      512
    );
  });

  it('renders outgoing callees and imports', () => {
    render(
      <NavigatorInspector
        impact={mockImpact}
        onSelectCaller={vi.fn()}
      />
    );

    expect(screen.getByText('LiteLLMGateway.execute_call')).toBeInTheDocument();
    expect(screen.getByText('fastapi.APIRouter')).toBeInTheDocument();
  });

  it('renders loading state when loading is true', () => {
    render(
      <NavigatorInspector
        impact={null}
        onSelectCaller={vi.fn()}
        loading={true}
      />
    );

    expect(screen.getByTestId('inspector-loading-skeleton')).toBeInTheDocument();
  });
});
