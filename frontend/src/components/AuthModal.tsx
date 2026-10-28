import React, { useState, useEffect } from 'react';
import {
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  checkAuthStatus,
  type AuthUser,
} from '../services/auth';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  authUser: AuthUser | null;
  isUnauthorized: boolean;
  onAuthSuccess?: () => void;
}

export function AuthModal({
  isOpen,
  onClose,
  authUser,
  isUnauthorized,
  onAuthSuccess,
}: AuthModalProps) {
  const [tokenInput, setTokenInput] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setTokenInput(getStoredToken() || '');
      setErrorMsg(null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMsg(null);

    const trimmed = tokenInput.trim();
    if (!trimmed) {
      clearStoredToken();
    } else {
      setStoredToken(trimmed);
    }

    const updatedUser = await checkAuthStatus();
    setIsSubmitting(false);

    if (updatedUser?.auth_enabled && !updatedUser.is_authenticated && trimmed) {
      setErrorMsg('Invalid API token or credential expired. Please check your key.');
    } else {
      if (onAuthSuccess) onAuthSuccess();
      onClose();
    }
  };

  const handleClear = async () => {
    clearStoredToken();
    setTokenInput('');
    await checkAuthStatus();
    setErrorMsg(null);
  };

  return (
    <div className="modal-backdrop" onClick={onClose} data-testid="auth-modal-backdrop">
      <div className="modal-content auth-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '520px' }}>
        <div className="modal-header">
          <h3>
            <i className="fa-solid fa-key" style={{ marginRight: '8px', color: 'var(--primary-color, #3b82f6)' }}></i>
            Authentication Token Manager
          </h3>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">
            <i className="fa-solid fa-xmark"></i>
          </button>
        </div>

        <div className="modal-body">
          {authUser?.auth_enabled ? (
            isUnauthorized ? (
              <div className="alert alert-warning" style={{ marginBottom: '16px' }} data-testid="auth-warning-alert">
                <i className="fa-solid fa-triangle-exclamation" style={{ marginRight: '8px' }}></i>
                <strong>Authentication Required:</strong> Requests to <code>/admin/api/*</code> are rejected (401/403). Please enter a valid API Key or Bearer token below.
              </div>
            ) : (
              <div className="alert alert-success" style={{ marginBottom: '16px' }} data-testid="auth-success-alert">
                <i className="fa-solid fa-circle-check" style={{ marginRight: '8px' }}></i>
                <strong>Authenticated:</strong> Role <code>{authUser.role}</code> ({authUser.auth_type}
                {authUser.user_id ? ` - ${authUser.user_id}` : ''})
              </div>
            )
          ) : (
            <div className="alert alert-info" style={{ marginBottom: '16px' }} data-testid="auth-disabled-alert">
              <i className="fa-solid fa-circle-info" style={{ marginRight: '8px' }}></i>
              <strong>AUTH_ENABLED=false:</strong> Local development bypass is active. All dashboard API calls pass automatically with admin role.
            </div>
          )}

          <form onSubmit={handleSave}>
            <div className="form-group" style={{ marginBottom: '16px' }}>
              <label htmlFor="auth-token-input" style={{ display: 'block', marginBottom: '6px', fontWeight: 500 }}>
                API Token / Bearer Token
              </label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  id="auth-token-input"
                  type={showToken ? 'text' : 'password'}
                  className="form-input"
                  placeholder="e.g. cc_live_..."
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  style={{ flex: 1 }}
                  data-testid="auth-token-input"
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowToken(!showToken)}
                  title={showToken ? 'Hide token' : 'Show token'}
                >
                  <i className={`fa-solid ${showToken ? 'fa-eye-slash' : 'fa-eye'}`}></i>
                </button>
              </div>
              <small className="form-help" style={{ marginTop: '6px', display: 'block', color: 'var(--text-muted, #94a3b8)' }}>
                Tokens starting with <code>cc_live_</code> or custom JWTs will be stored in local browser storage and included as <code>Authorization: Bearer &lt;token&gt;</code> on API calls.
              </small>
            </div>

            {errorMsg && (
              <div className="alert alert-danger" style={{ marginBottom: '16px' }} data-testid="auth-error-message">
                <i className="fa-solid fa-circle-exclamation" style={{ marginRight: '8px' }}></i>
                {errorMsg}
              </div>
            )}

            <div className="modal-actions" style={{ display: 'flex', justifyContent: 'space-between', marginTop: '20px' }}>
              <button
                type="button"
                className="btn btn-danger"
                onClick={handleClear}
                disabled={!tokenInput && !getStoredToken()}
                data-testid="clear-token-btn"
              >
                <i className="fa-solid fa-trash-can" style={{ marginRight: '6px' }}></i>
                Clear Token
              </button>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="button" className="btn btn-secondary" onClick={onClose}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={isSubmitting}
                  data-testid="save-token-btn"
                >
                  {isSubmitting ? (
                    <>
                      <i className="fa-solid fa-spinner fa-spin" style={{ marginRight: '6px' }}></i> Validating...
                    </>
                  ) : (
                    <>
                      <i className="fa-solid fa-floppy-disk" style={{ marginRight: '6px' }}></i> Save &amp; Apply
                    </>
                  )}
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
