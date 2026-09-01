import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { NavigatorTree } from '../components/navigator/NavigatorTree';
import type { NavigatorTreeNode } from '../components/navigator/types';

const mockTreeData: NavigatorTreeNode[] = [
  {
    id: 'dir:app',
    name: 'app',
    is_dir: true,
    path: 'app',
    symbol_count: 5,
    route_count: 2,
    children: [
      {
        id: 'dir:app/routers',
        name: 'routers',
        is_dir: true,
        path: 'app/routers',
        symbol_count: 3,
        route_count: 2,
        children: [
          {
            id: 'file:app/routers/chat.py',
            name: 'chat.py',
            is_dir: false,
            path: 'app/routers/chat.py',
            language: 'python',
            symbol_count: 3,
            route_count: 2,
          },
        ],
      },
      {
        id: 'file:app/utils.ts',
        name: 'utils.ts',
        is_dir: false,
        path: 'app/utils.ts',
        language: 'typescript',
        symbol_count: 2,
        route_count: 0,
      },
    ],
  },
  {
    id: 'file:README.md',
    name: 'README.md',
    is_dir: false,
    path: 'README.md',
    language: 'markdown',
    symbol_count: 0,
    route_count: 0,
  },
];

describe('NavigatorTree Component', () => {
  it('renders directory nodes and root files', () => {
    render(
      <NavigatorTree
        nodes={mockTreeData}
        selectedPath={null}
        onSelectFile={vi.fn()}
      />
    );

    expect(screen.getByText('app')).toBeInTheDocument();
    expect(screen.getByText('README.md')).toBeInTheDocument();
  });

  it('expands and collapses directory nodes on click', () => {
    render(
      <NavigatorTree
        nodes={mockTreeData}
        selectedPath={null}
        onSelectFile={vi.fn()}
      />
    );

    // Initial root shows 'app' directory
    const appDir = screen.getByText('app');
    expect(appDir).toBeInTheDocument();

    // Click 'app' to expand
    fireEvent.click(appDir);
    expect(screen.getByText('routers')).toBeInTheDocument();
    expect(screen.getByText('utils.ts')).toBeInTheDocument();

    // Click 'routers' to expand
    fireEvent.click(screen.getByText('routers'));
    expect(screen.getByText('chat.py')).toBeInTheDocument();

    // Click 'routers' again to collapse
    fireEvent.click(screen.getByText('routers'));
    expect(screen.queryByText('chat.py')).not.toBeInTheDocument();
  });

  it('displays symbol count and route count badges', () => {
    render(
      <NavigatorTree
        nodes={mockTreeData}
        selectedPath={null}
        onSelectFile={vi.fn()}
      />
    );

    // Open app and routers
    fireEvent.click(screen.getByText('app'));
    fireEvent.click(screen.getByText('routers'));

    // Check symbol count badge for chat.py
    const chatFile = screen.getByText('chat.py').closest('.nav-tree-item');
    expect(chatFile).toHaveTextContent('3 sym');
    expect(chatFile).toHaveTextContent('2 rts');
  });

  it('calls onSelectFile when a file node is clicked', () => {
    const handleSelectFile = vi.fn();
    render(
      <NavigatorTree
        nodes={mockTreeData}
        selectedPath={null}
        onSelectFile={handleSelectFile}
      />
    );

    fireEvent.click(screen.getByText('README.md'));
    expect(handleSelectFile).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'file:README.md',
        path: 'README.md',
        is_dir: false,
      })
    );
  });

  it('highlights the selected file', () => {
    render(
      <NavigatorTree
        nodes={mockTreeData}
        selectedPath="README.md"
        onSelectFile={vi.fn()}
      />
    );

    const readmeItem = screen.getByText('README.md').closest('.nav-tree-item');
    expect(readmeItem).toHaveClass('selected');
  });

  it('filters nodes based on search input', () => {
    render(
      <NavigatorTree
        nodes={mockTreeData}
        selectedPath={null}
        onSelectFile={vi.fn()}
      />
    );

    const searchInput = screen.getByPlaceholderText(/search files/i);
    fireEvent.change(searchInput, { target: { value: 'chat' } });

    // With filter active, chat.py and its parent dirs should automatically be visible
    expect(screen.getByText('chat.py')).toBeInTheDocument();
    expect(screen.queryByText('utils.ts')).not.toBeInTheDocument();
    expect(screen.queryByText('README.md')).not.toBeInTheDocument();
  });

  it('handles expand all and collapse all buttons', () => {
    render(
      <NavigatorTree
        nodes={mockTreeData}
        selectedPath={null}
        onSelectFile={vi.fn()}
      />
    );

    const expandAllBtn = screen.getByTitle(/expand all/i);
    fireEvent.click(expandAllBtn);

    expect(screen.getByText('chat.py')).toBeInTheDocument();
    expect(screen.getByText('utils.ts')).toBeInTheDocument();

    const collapseAllBtn = screen.getByTitle(/collapse all/i);
    fireEvent.click(collapseAllBtn);

    expect(screen.queryByText('chat.py')).not.toBeInTheDocument();
    expect(screen.queryByText('utils.ts')).not.toBeInTheDocument();
  });

  it('supports keyboard navigation up/down/enter', () => {
    const handleSelectFile = vi.fn();
    render(
      <NavigatorTree
        nodes={mockTreeData}
        selectedPath={null}
        onSelectFile={handleSelectFile}
      />
    );

    const container = screen.getByTestId('navigator-tree-container');
    
    // Focus and press down arrow
    fireEvent.keyDown(container, { key: 'ArrowDown' });
    fireEvent.keyDown(container, { key: 'Enter' });

    // First item is 'app' (dir), so Enter toggles expansion
    expect(screen.getByText('utils.ts')).toBeInTheDocument();

    // Navigate to README.md
    fireEvent.keyDown(container, { key: 'ArrowDown' });
    fireEvent.keyDown(container, { key: 'ArrowDown' });
    fireEvent.keyDown(container, { key: 'ArrowDown' });
    fireEvent.keyDown(container, { key: 'Enter' });

    expect(handleSelectFile).toHaveBeenCalled();
  });

  it('renders loading state when loading is true', () => {
    render(
      <NavigatorTree
        nodes={[]}
        selectedPath={null}
        onSelectFile={vi.fn()}
        loading={true}
      />
    );

    expect(screen.getByTestId('tree-loading-spinner')).toBeInTheDocument();
  });
});
