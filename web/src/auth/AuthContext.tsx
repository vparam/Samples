import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ApiError, api } from '../api/client';
import type { User } from '../types';

type Status = 'loading' | 'anon' | 'authed';

interface AuthState {
  status: Status;
  user: User | null;
  error: string | null;
  login: (email: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<User>('/api/auth/me')
      .then((u) => {
        setUser(u);
        setStatus('authed');
      })
      .catch(() => {
        setUser(null);
        setStatus('anon');
      });
  }, []);

  const login = useCallback(async (email: string) => {
    setError(null);
    try {
      const u = await api.post<User>('/api/auth/login', { email });
      setUser(u);
      setStatus('authed');
    } catch (e) {
      const msg = e instanceof ApiError ? e.detail : 'Sign-in failed';
      setError(msg);
      throw e;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/api/auth/logout');
    } finally {
      setUser(null);
      setStatus('anon');
    }
  }, []);

  return (
    <AuthCtx.Provider value={{ status, user, error, login, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
