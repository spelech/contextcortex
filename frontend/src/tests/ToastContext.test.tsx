import { render, screen, act, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ToastProvider, useToast } from '../ToastContext';

function TestConsumer() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.success('Success message')}>Trigger Success</button>
      <button onClick={() => toast.error('Error message')}>Trigger Error</button>
      <button onClick={() => toast.info('Info message')}>Trigger Info</button>
      <button onClick={() => toast.warning('Warning message')}>Trigger Warning</button>
      <button onClick={() => toast.showToast('Generic message', 'info')}>Trigger ShowToast</button>
    </div>
  );
}

describe('ToastContext', () => {
  it('throws error when useToast is called outside of ToastProvider', () => {
    // Suppress console.error for expected React hook error
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow('useToast must be used within a ToastProvider');
    spy.mockRestore();
  });

  it('displays success toast and auto-dismisses after timeout', () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <TestConsumer />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Trigger Success').click();
    });

    expect(screen.getByText('Success message')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(4000);
    });

    expect(screen.queryByText('Success message')).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it('displays error, info, and warning toasts with appropriate CSS classes and icons', () => {
    render(
      <ToastProvider>
        <TestConsumer />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Trigger Error').click();
      screen.getByText('Trigger Info').click();
      screen.getByText('Trigger Warning').click();
    });

    const errorMsg = screen.getByText('Error message');
    const infoMsg = screen.getByText('Info message');
    const warnMsg = screen.getByText('Warning message');

    expect(errorMsg).toBeInTheDocument();
    expect(infoMsg).toBeInTheDocument();
    expect(warnMsg).toBeInTheDocument();

    expect(errorMsg.closest('.toast')).toHaveClass('toast-error');
    expect(infoMsg.closest('.toast')).toHaveClass('toast-info');
    expect(warnMsg.closest('.toast')).toHaveClass('toast-warning');
  });

  it('supports showToast method with customizable toast types', () => {
    render(
      <ToastProvider>
        <TestConsumer />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Trigger ShowToast').click();
    });

    expect(screen.getByText('Generic message')).toBeInTheDocument();
  });

  it('dismisses toast immediately when clicking dismiss button', () => {
    render(
      <ToastProvider>
        <TestConsumer />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Trigger Success').click();
    });

    expect(screen.getByText('Success message')).toBeInTheDocument();

    const dismissBtn = screen.getByRole('button', { name: /Dismiss notification/i });
    fireEvent.click(dismissBtn);

    expect(screen.queryByText('Success message')).not.toBeInTheDocument();
  });
});
