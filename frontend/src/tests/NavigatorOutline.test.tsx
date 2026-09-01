import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { NavigatorOutline } from '../components/navigator/NavigatorOutline';
import type { FileOutline } from '../components/navigator/types';


const mockOutline: FileOutline = {
  repo: 'model-context-gateway',
  filepath: 'app/api/routers/chat.py',
  language: 'python',
  symbols: [
    {
      id: 101,
      name: 'ChatService',
      full_symbol: 'app.api.routers.chat.ChatService',
      kind: 'class',
      start_line: 10,
      end_line: 50,
      signature: 'class ChatService:',
    },
    {
      id: 102,
      name: 'chat_completion_endpoint',
      full_symbol: 'app.api.routers.chat.chat_completion_endpoint',
      kind: 'function',
      start_line: 55,
      end_line: 90,
      signature: 'async def chat_completion_endpoint(request: Request) -> Response',
      route: {
        http_method: 'POST',
        path_pattern: '/v1/chat/completions',
        framework: 'FastAPI',
      },
    },
    {
      id: 103,
      name: 'health_check',
      full_symbol: 'app.api.routers.chat.health_check',
      kind: 'function',
      start_line: 95,
      end_line: 105,
      signature: 'def health_check() -> dict',
      route: {
        http_method: 'GET',
        path_pattern: '/healthz',
        framework: 'FastAPI',
      },
    },
    {
      id: 104,
      name: 'validate_payload',
      full_symbol: 'app.api.routers.chat.validate_payload',
      kind: 'function',
      start_line: 110,
      end_line: 125,
      signature: 'def validate_payload(data: dict) -> bool',
    },
  ],
};

describe('NavigatorOutline Component', () => {
  it('renders empty placeholder when outline is null or empty', () => {
    const { rerender } = render(
      <NavigatorOutline
        outline={null}
        selectedSymbolId={null}
        onSelectSymbol={vi.fn()}
      />
    );

    expect(screen.getByText(/no file selected/i)).toBeInTheDocument();

    rerender(
      <NavigatorOutline
        outline={{ repo: 'repo', filepath: 'empty.py', symbols: [] }}
        selectedSymbolId={null}
        onSelectSymbol={vi.fn()}
      />
    );

    expect(screen.getByText(/no symbols found in this file/i)).toBeInTheDocument();
  });

  it('renders file header with filepath and symbols', () => {
    render(
      <NavigatorOutline
        outline={mockOutline}
        selectedSymbolId={null}
        onSelectSymbol={vi.fn()}
      />
    );

    expect(screen.getByText('chat.py')).toBeInTheDocument();
    expect(screen.getByText('ChatService')).toBeInTheDocument();
    expect(screen.getByText('chat_completion_endpoint')).toBeInTheDocument();
    expect(screen.getByText('health_check')).toBeInTheDocument();
    expect(screen.getByText('validate_payload')).toBeInTheDocument();
  });

  it('renders route badges for route symbols', () => {
    render(
      <NavigatorOutline
        outline={mockOutline}
        selectedSymbolId={null}
        onSelectSymbol={vi.fn()}
      />
    );

    expect(screen.getByText('POST')).toBeInTheDocument();
    expect(screen.getByText('/v1/chat/completions')).toBeInTheDocument();
    expect(screen.getByText('GET')).toBeInTheDocument();
    expect(screen.getByText('/healthz')).toBeInTheDocument();
  });

  it('filters symbols by category chips', () => {
    render(
      <NavigatorOutline
        outline={mockOutline}
        selectedSymbolId={null}
        onSelectSymbol={vi.fn()}
      />
    );

    // Filter by Routes
    fireEvent.click(screen.getByRole('button', { name: /routes/i }));
    expect(screen.getByText('chat_completion_endpoint')).toBeInTheDocument();
    expect(screen.getByText('health_check')).toBeInTheDocument();
    expect(screen.queryByText('ChatService')).not.toBeInTheDocument();
    expect(screen.queryByText('validate_payload')).not.toBeInTheDocument();

    // Filter by Classes
    fireEvent.click(screen.getByRole('button', { name: /classes/i }));
    expect(screen.getByText('ChatService')).toBeInTheDocument();
    expect(screen.queryByText('chat_completion_endpoint')).not.toBeInTheDocument();

    // Filter by Functions
    fireEvent.click(screen.getByRole('button', { name: /functions/i }));
    expect(screen.getByText('validate_payload')).toBeInTheDocument();
    expect(screen.queryByText('ChatService')).not.toBeInTheDocument();

    // Back to All
    fireEvent.click(screen.getByRole('button', { name: /all/i }));
    expect(screen.getByText('ChatService')).toBeInTheDocument();
    expect(screen.getByText('chat_completion_endpoint')).toBeInTheDocument();
  });

  it('filters symbols using the search input', () => {
    render(
      <NavigatorOutline
        outline={mockOutline}
        selectedSymbolId={null}
        onSelectSymbol={vi.fn()}
      />
    );

    const searchInput = screen.getByPlaceholderText(/filter symbols/i);
    fireEvent.change(searchInput, { target: { value: 'validate' } });

    expect(screen.getByText('validate_payload')).toBeInTheDocument();
    expect(screen.queryByText('ChatService')).not.toBeInTheDocument();
    expect(screen.queryByText('chat_completion_endpoint')).not.toBeInTheDocument();
  });

  it('calls onSelectSymbol when a symbol item is clicked', () => {
    const handleSelectSymbol = vi.fn();
    render(
      <NavigatorOutline
        outline={mockOutline}
        selectedSymbolId={null}
        onSelectSymbol={handleSelectSymbol}
      />
    );

    fireEvent.click(screen.getByText('chat_completion_endpoint'));
    expect(handleSelectSymbol).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 102,
        name: 'chat_completion_endpoint',
      })
    );
  });

  it('highlights the selected symbol card', () => {
    render(
      <NavigatorOutline
        outline={mockOutline}
        selectedSymbolId={102}
        onSelectSymbol={vi.fn()}
      />
    );

    const activeCard = screen.getByTestId('symbol-item-102');
    expect(activeCard).toHaveClass('active');
  });

  it('renders loading skeleton when loading is true', () => {
    render(
      <NavigatorOutline
        outline={null}
        selectedSymbolId={null}
        onSelectSymbol={vi.fn()}
        loading={true}
      />
    );

    expect(screen.getByTestId('outline-loading-skeleton')).toBeInTheDocument();
  });
});
