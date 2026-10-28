/**
 * Authentication Service and Fetch Interceptor for ContextCortex Admin Dashboard.
 * Manages API token persistence, auth status checks, and automatic request signing.
 */

export const TOKEN_STORAGE_KEY = 'contextcortex_auth_token';

export interface AuthUser {
  auth_enabled: boolean;
  is_authenticated: boolean;
  user_id: string | null;
  name: string | null;
  role: string;
  scopes: string[];
  auth_type: string;
  key_id: number | null;
  group_name: string | null;
}

export type AuthListener = (user: AuthUser | null, isUnauthorized: boolean) => void;

let currentAuthUser: AuthUser | null = null;
let isUnauthorizedState = false;
const authListeners: Set<AuthListener> = new Set();

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch (e) {
    console.error('Error reading auth token from localStorage:', e);
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token && token.trim()) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token.trim());
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch (e) {
    console.error('Error setting auth token in localStorage:', e);
  }
}

export function clearStoredToken(): void {
  setStoredToken(null);
}

export function subscribeAuth(listener: AuthListener): () => void {
  authListeners.add(listener);
  listener(currentAuthUser, isUnauthorizedState);
  return () => {
    authListeners.delete(listener);
  };
}

function notifyAuthListeners() {
  authListeners.forEach((listener) => listener(currentAuthUser, isUnauthorizedState));
}

export function setUnauthorizedState(unauthorized: boolean) {
  isUnauthorizedState = unauthorized;
  notifyAuthListeners();
}

export function getCurrentAuthUser(): AuthUser | null {
  return currentAuthUser;
}

export function getIsUnauthorized(): boolean {
  return isUnauthorizedState;
}

function getFetch(): typeof fetch {
  if (typeof window !== 'undefined' && window.fetch && window.fetch !== authFetch) {
    return window.fetch;
  }
  return authFetch._rawFetch || globalThis.fetch;
}

/**
 * Checks current auth status from /admin/api/auth/me
 */
export async function checkAuthStatus(): Promise<AuthUser | null> {
  try {
    const token = getStoredToken();
    const headers: Record<string, string> = {
      'Accept': 'application/json',
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const fetchFn = getFetch();
    const response = await fetchFn('/admin/api/auth/me', {
      method: 'GET',
      headers,
    });

    if (response.status === 401 || response.status === 403) {
      isUnauthorizedState = true;
      currentAuthUser = {
        auth_enabled: true,
        is_authenticated: false,
        user_id: null,
        name: null,
        role: 'none',
        scopes: [],
        auth_type: 'none',
        key_id: null,
        group_name: null,
      };
      notifyAuthListeners();
      return currentAuthUser;
    }

    if (!response.ok) {
      return null;
    }

    const data: AuthUser = await response.json();
    currentAuthUser = data;
    if (data.is_authenticated) {
      isUnauthorizedState = false;
    }
    notifyAuthListeners();
    return data;
  } catch (e) {
    console.error('Error checking auth status:', e);
    return null;
  }
}

interface AuthFetchType {
  (input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
  _rawFetch?: typeof fetch;
}

/**
 * Authenticated fetch wrapper.
 * Injects Authorization header into /admin/api/* requests if token exists,
 * and intercepts 401/403 responses to trigger login prompts.
 */
export const authFetch: AuthFetchType = async function (
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const token = getStoredToken();
  const urlStr = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;

  const isApiRequest = urlStr.startsWith('/admin/api/') || urlStr.includes('/admin/api/');

  let modifiedInit = init ? { ...init } : {};

  if (isApiRequest && token) {
    const headers = new Headers(modifiedInit.headers || {});
    if (!headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    modifiedInit.headers = headers;
  }

  const rawFetch = authFetch._rawFetch || (typeof window !== 'undefined' ? window.fetch : globalThis.fetch);
  const response = await rawFetch(input, modifiedInit);

  if (isApiRequest && (response.status === 401 || response.status === 403)) {
    isUnauthorizedState = true;
    if (currentAuthUser) {
      currentAuthUser = { ...currentAuthUser, is_authenticated: false };
    }
    notifyAuthListeners();
  }

  return response;
};

authFetch._rawFetch = typeof window !== 'undefined' ? window.fetch : globalThis.fetch;

/**
 * Install patch on window.fetch so that all existing components automatically use authFetch.
 */
export function setupGlobalFetchInterceptor() {
  if (typeof window !== 'undefined' && window.fetch !== authFetch) {
    authFetch._rawFetch = window.fetch;
    window.fetch = authFetch;
  }
}
