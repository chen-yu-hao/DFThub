import { createContext, useContext, useState, useEffect, useCallback } from "react";
import type { ReactNode } from "react";
import axios from "axios";

interface User {
  id: number;
  username: string;
  email: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  login: (email: string, password: string) => Promise<string | null>;
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

  useEffect(() => {
    installInterceptor();
    const saved = localStorage.getItem(TOKEN_KEY);
    if (saved) {
      setLoading(true);
      setToken(saved);
      axios
        .get("/api_dft/me", { headers: { Authorization: `Bearer ${saved}` } })
        .then((r) => {
          if (r.data.success) setUser(r.data.user);
          else localStorage.removeItem(TOKEN_KEY);
        })
        .catch(() => localStorage.removeItem(TOKEN_KEY))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<string | null> => {
    try {
      const r = await axios.post("/api_dft/login", { email, password });
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
        const r = await axios.post("/api_dft/register", { username, email, password });
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
      value={{ user, token, isAuthenticated: !!user, loading, login, register, logout, showAuthModal, setShowAuthModal }}
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
