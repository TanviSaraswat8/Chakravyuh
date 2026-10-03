import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { auth, type User } from "./api";

interface AuthState { user: User | null; ready: boolean; refresh: () => Promise<void>; setUser: (u: User | null) => void }

const Ctx = createContext<AuthState>({ user: null, ready: false, refresh: async () => {}, setUser: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const refresh = useCallback(async () => {
    try { setUser(await auth.me()); } catch { setUser(null); } finally { setReady(true); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return <Ctx.Provider value={{ user, ready, refresh, setUser }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
export const can = (u: User | null, permission: string) => !!u && u.permissions.includes(permission);
