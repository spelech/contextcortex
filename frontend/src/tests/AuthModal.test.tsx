import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AuthModal } from '../components/AuthModal';
import {
  setStoredToken,
  getStoredToken,
  clearStoredToken,
  TOKEN_STORAGE_KEY,
} from '../services/auth';

describe('AuthModal Component & Auth Service', () => {
  beforeEach(() => {
    clearStoredToken();
    vi.restoreAllMocks();
  });

  it('manages localStorage token read/write/clear correctly', () => {
    expect(getStoredToken()).toBeNull();
    setStoredToken('cc_live_test_key_123');
    expect(getStoredToken()).toBe('cc_live_test_key_123');
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('cc_live_test_key_123');
    clearStoredToken();
    expect(getStoredToken()).toBeNull();
  });

  it('renders AuthModal when isOpen is true', () => {
    render(
      <AuthModal
        isOpen={true}
        onClose={vi.fn()}
        authUser={{
          auth_enabled: false,
          is_authenticated: true,
          user_id: 'anonymous',
          name: 'Dev',
          role: 'admin',
          scopes: [],
          auth_type: 'bypass',
          key_id: null,
          group_name: null,
        }}
        isUnauthorized={false}
      />
    );

    expect(screen.getByText('Authentication Token Manager')).toBeInTheDocument();
    expect(screen.getByTestId('auth-disabled-alert')).toBeInTheDocument();
  });

  it('shows warning alert when AUTH_ENABLED=true and isUnauthorized=true', () => {
    render(
      <AuthModal
        isOpen={true}
        onClose={vi.fn()}
        authUser={{
          auth_enabled: true,
          is_authenticated: false,
          user_id: null,
          name: null,
          role: 'none',
          scopes: [],
          auth_type: 'none',
          key_id: null,
          group_name: null,
        }}
        isUnauthorized={true}
      />
    );

    expect(screen.getByTestId('auth-warning-alert')).toBeInTheDocument();
    expect(screen.getByText(/Authentication Required/i)).toBeInTheDocument();
  });

  it('allows saving token and calling checkAuthStatus', async () => {
    const onClose = vi.fn();
    const onAuthSuccess = vi.fn();

    vi.spyOn(globalThis, 'fetch').mockImplementation((url: any) => {
      if (url === '/admin/api/auth/me') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            auth_enabled: true,
            is_authenticated: true,
            user_id: 'key-1',
            name: 'Test Key',
            role: 'editor',
            scopes: ['mcp:editor'],
            auth_type: 'api_key',
            key_id: 1,
            group_name: null,
          }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(
      <AuthModal
        isOpen={true}
        onClose={onClose}
        authUser={{
          auth_enabled: true,
          is_authenticated: false,
          user_id: null,
          name: null,
          role: 'none',
          scopes: [],
          auth_type: 'none',
          key_id: null,
          group_name: null,
        }}
        isUnauthorized={true}
        onAuthSuccess={onAuthSuccess}
      />
    );

    const input = screen.getByTestId('auth-token-input');
    fireEvent.change(input, { target: { value: 'cc_live_valid_token_777' } });

    const saveBtn = screen.getByTestId('save-token-btn');
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(getStoredToken()).toBe('cc_live_valid_token_777');
      expect(onAuthSuccess).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('handles clearing token via Clear Token button', async () => {
    setStoredToken('cc_live_old_token');
    vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      Promise.resolve({
        ok: false,
        status: 401,
      } as Response)
    );

    render(
      <AuthModal
        isOpen={true}
        onClose={vi.fn()}
        authUser={null}
        isUnauthorized={true}
      />
    );

    const clearBtn = screen.getByTestId('clear-token-btn');
    fireEvent.click(clearBtn);

    await waitFor(() => {
      expect(getStoredToken()).toBeNull();
    });
  });
});
