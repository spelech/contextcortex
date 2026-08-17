import { render, screen, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ToastProvider, useToast } from '../ToastContext';

function TestConsumer() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.success('Success message')}>Trigger Success</button>
      <button onClick={() => toast.error('Error message')}>Trigger Error</button>
      <button onClick={() => toast.info('Info message')}>Trigger Info</button>
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

  it('displays error and info toasts with appropriate CSS classes', () => {
    render(
      <ToastProvider>
        <TestConsumer />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Trigger Error').click();
      screen.getByText('Trigger Info').click();
    });

    expect(screen.getByText('Error message')).toBeInTheDocument();
    expect(screen.getByText('Info message')).toBeInTheDocument();
  });
});
