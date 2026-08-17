import { createContext, useContext, useState, useCallback, useMemo } from 'react';
import type { ReactNode } from 'react';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

export interface ToastContextType {
  toast: {
    success: (msg: string) => void;
    error: (msg: string) => void;
    info: (msg: string) => void;
    warning: (msg: string) => void;
    showToast: (msg: string, type?: ToastType) => void;
    dismiss: (id: number) => void;
  };
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used within a ToastProvider');
  return context.toast;
}

let toastCounter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = ++toastCounter;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  const toast = useMemo(
    () => ({
      success: (msg: string) => addToast(msg, 'success'),
      error: (msg: string) => addToast(msg, 'error'),
      info: (msg: string) => addToast(msg, 'info'),
      warning: (msg: string) => addToast(msg, 'warning'),
      showToast: (msg: string, type?: ToastType) => addToast(msg, type || 'info'),
      dismiss,
    }),
    [addToast, dismiss]
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="toast-container" aria-live="polite" aria-atomic="true">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`} role="status">
            {t.type === 'error' && <i className="fa-solid fa-circle-exclamation" aria-hidden="true"></i>}
            {t.type === 'success' && <i className="fa-solid fa-circle-check" aria-hidden="true"></i>}
            {t.type === 'info' && <i className="fa-solid fa-circle-info" aria-hidden="true"></i>}
            {t.type === 'warning' && <i className="fa-solid fa-triangle-exclamation" aria-hidden="true"></i>}
            <span className="toast-message">{t.message}</span>
            <button
              type="button"
              className="toast-dismiss-btn"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              title="Dismiss"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true"></i>
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
