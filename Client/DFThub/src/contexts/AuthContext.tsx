import { createContext, useContext, useState, useEffect, useCallback } from "react";
import type { ReactNode } from "react";
import axios from "axios";

interface User {
  id: number;
  username: string;
  email: string | null;
}

/** Public server settings from /api_dft/features. */
export interface Features {
  /** The server e-mails job notifications. */
  mail: boolean;
  /** Local single-user mode (dfthub serve --local): the server starts the session, nobody signs in. */
  local: boolean;
}

const DEFAULT_FEATURES: Features = { mail: false, local: false };

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  features: Features;
  login: (identifier: string, password: string) => Promise<string | null>;
  register: (username: string, email: string, password: string) => Promise<string | null>;
  logout: () => void;
  showAuthModal: boolean;
  setShowAuthModal: (show: boolean) => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

const TOKEN_KEY = "auth_token";

// Axios interceptor — runs once on module load
let _interceptorInstalled = false;
function installInterceptor() {
  if (_interceptorInstalled) return;
  _interceptorInstalled = true;
  axios.interceptors.request.use((config) => {
    const t = localStorage.getItem(TOKEN_KEY);
    if (t) config.headers.Authorization = `Bearer ${t}`;
    return config;
  });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  // Keep the server and first client render identical; session restoration starts in the effect.
  const [loading, setLoading] = useState(false);
  const [showAuthModal, setShowAuthModal] = useState(false);
  // Until the server answers, assume no mail and ordinary sign-in.
  const [features, setFeatures] = useState<Features>(DEFAULT_FEATURES);

  useEffect(() => {
    installInterceptor();
    let active = true;
    const saved = localStorage.getItem(TOKEN_KEY);
    setLoading(true);
    if (saved) setToken(saved);
    // Ask for the server settings and check a saved session at the same time.
    const featuresRequest = axios.get("/api_dft/features")
      .then((r): Features => ({ mail: r.data?.mail === true, local: r.data?.local === true }))
      .catch(() => DEFAULT_FEATURES);
    const savedUser = saved
      ? axios.get("/api_dft/me", { headers: { Authorization: `Bearer ${saved}` } })
        .then((r): User | null => (r.data.success ? r.data.user : null))
        .catch(() => null)
      : Promise.resolve(null);

    async function start() {
      const next = await featuresRequest;
      if (!active) return;
      setFeatures(next);
      if (next.local) {
        // Local single-user mode: the server hands out the session.
        try {
          const r = await axios.post("/api_dft/local-session");
          if (active && r.data.success) {
            localStorage.setItem(TOKEN_KEY, r.data.token);
            setToken(r.data.token);
            setUser(r.data.user);
            return;
          }
        } catch { /* Reported by the page as a failed local session. */ }
        if (active) { localStorage.removeItem(TOKEN_KEY); setToken(null); setUser(null); }
        return;
      }
      const restored = await savedUser;
      if (!active) return;
      if (restored) setUser(restored);
      else if (saved) { localStorage.removeItem(TOKEN_KEY); setToken(null); }
    }
    start().finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const login = useCallback(async (identifier: string, password: string): Promise<string | null> => {
    try {
      const r = await axios.post("/api_dft/login", { login: identifier, password });
      if (r.data.success) {
        localStorage.setItem(TOKEN_KEY, r.data.token);
        setToken(r.data.token);
        setUser(r.data.user);
        setShowAuthModal(false);
        return null;
      }
      return r.data.msg || "Login failed";
    } catch (e: any) {
      return e.response?.data?.msg || "Login failed";
    }
  }, []);

  const register = useCallback(
    async (username: string, email: string, password: string): Promise<string | null> => {
      try {
        const r = await axios.post("/api_dft/register", { username, password, ...(email ? { email } : {}) });
        if (r.data.success) {
          localStorage.setItem(TOKEN_KEY, r.data.token);
          setToken(r.data.token);
          setUser(r.data.user);
          setShowAuthModal(false);
          return null;
        }
        return r.data.msg || "Registration failed";
      } catch (e: any) {
        return e.response?.data?.msg || "Registration failed";
      }
    },
    []
  );

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, token, isAuthenticated: !!user, loading, features, login, register, logout, showAuthModal, setShowAuthModal }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
