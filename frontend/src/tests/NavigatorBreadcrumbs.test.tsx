import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NavigatorBreadcrumbs } from '../components/navigator/NavigatorBreadcrumbs';

describe('NavigatorBreadcrumbs Component', () => {
  it('renders repo badge and clickable path segments', () => {
    const onNavigatePath = vi.fn();
    render(
      <NavigatorBreadcrumbs
        repo="my-repo"
        path="src/components/Button.tsx"
        symbol="Button"
        onNavigatePath={onNavigatePath}
        canGoBack={true}
        canGoForward={false}
        onGoBack={vi.fn()}
        onGoForward={vi.fn()}
        onToggleSidebar={vi.fn()}
        isSidebarOpen={true}
      />
    );

    expect(screen.getByText('my-repo')).toBeInTheDocument();
    expect(screen.getByText('src')).toBeInTheDocument();
    expect(screen.getByText('components')).toBeInTheDocument();
    expect(screen.getByText('Button.tsx')).toBeInTheDocument();
    expect(screen.getByText('Button')).toBeInTheDocument();

    fireEvent.click(screen.getByText('src'));
    expect(onNavigatePath).toHaveBeenCalledWith('src');

    fireEvent.click(screen.getByText('components'));
    expect(onNavigatePath).toHaveBeenCalledWith('src/components');
  });

  it('triggers back and forward history buttons', () => {
    const onGoBack = vi.fn();
    const onGoForward = vi.fn();
    render(
      <NavigatorBreadcrumbs
        repo="my-repo"
        path="app/main.py"
        symbol={null}
        onNavigatePath={vi.fn()}
        canGoBack={true}
        canGoForward={true}
        onGoBack={onGoBack}
        onGoForward={onGoForward}
        onToggleSidebar={vi.fn()}
        isSidebarOpen={true}
      />
    );

    const backBtn = screen.getByRole('button', { name: /go back/i });
    const forwardBtn = screen.getByRole('button', { name: /go forward/i });

    expect(backBtn).not.toBeDisabled();
    expect(forwardBtn).not.toBeDisabled();

    fireEvent.click(backBtn);
    expect(onGoBack).toHaveBeenCalledTimes(1);

    fireEvent.click(forwardBtn);
    expect(onGoForward).toHaveBeenCalledTimes(1);
  });

  it('disables history buttons when navigation history bounds are reached', () => {
    render(
      <NavigatorBreadcrumbs
        repo="my-repo"
        path="app/main.py"
        symbol={null}
        onNavigatePath={vi.fn()}
        canGoBack={false}
        canGoForward={false}
        onGoBack={vi.fn()}
        onGoForward={vi.fn()}
        onToggleSidebar={vi.fn()}
        isSidebarOpen={true}
      />
    );

    expect(screen.getByRole('button', { name: /go back/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /go forward/i })).toBeDisabled();
  });

  it('toggles sidebar on sidebar button click', () => {
    const onToggleSidebar = vi.fn();
    render(
      <NavigatorBreadcrumbs
        repo="my-repo"
        path={null}
        symbol={null}
        onNavigatePath={vi.fn()}
        canGoBack={false}
        canGoForward={false}
        onGoBack={vi.fn()}
        onGoForward={vi.fn()}
        onToggleSidebar={onToggleSidebar}
        isSidebarOpen={false}
      />
    );

    const toggleBtn = screen.getByRole('button', { name: /expand sidebar/i });
    fireEvent.click(toggleBtn);
    expect(onToggleSidebar).toHaveBeenCalledTimes(1);
  });
});
