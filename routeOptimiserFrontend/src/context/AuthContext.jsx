/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, getAuthToken, setAuthToken } from "../api/client";

/*
  Who is signed in, and what they are allowed to decide.

  The permissions exposed here are for *rendering* only — showing a verifier the Verify
  button and not showing it to a reporter. They are not the enforcement. Every one of these
  rules is checked again server-side in src/api/auth.py, because a control that is merely
  hidden is not a control: anyone can open devtools or curl the endpoint. Keeping both
  copies is duplication with a purpose — the server decides, the client explains.
*/

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(getAuthToken()));

  // A stored token may have expired while the tab was closed; ask the server rather than
  // trusting it and showing controls that will 401 on first use.
  useEffect(() => {
    if (!getAuthToken()) return;
    let cancelled = false;
    api
      .me()
      .then((r) => !cancelled && setUser(r.user))
      .catch(() => {
        setAuthToken(null);
        if (!cancelled) setUser(null);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username, password) => {
    const result = await api.login(username, password);
    setAuthToken(result.token);
    setUser(result.user);
    return result.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // A failed logout call must still clear the local session.
    }
    setAuthToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => {
    const role = user?.role || null;
    const canDecide = role === "verifier" || role === "controller";
    return {
      user,
      role,
      loading,
      login,
      logout,
      isSignedIn: Boolean(user),
      // Presentation-level permissions. The server is the authority.
      can: {
        verify: canDecide,
        resolve: canDecide,
        delete: role === "controller",
        seeReviewQueue: canDecide,
      },
      /** Would this user be refused, and why? Used to explain a disabled control rather
       *  than silently hiding it — an operator who cannot act should know who can. */
      refusalFor(incident, action) {
        if (!user) return "Sign in to act on reports.";
        if (action === "delete" && role !== "controller")
          return "Only a State Controller can delete a report.";
        if (!canDecide)
          return "Field Reporters submit reports; a District Verifier reviews them.";
        if (incident?.reported_by_id && incident.reported_by_id === user.id)
          return "You filed this report, so someone else must confirm it.";
        return null;
      },
    };
  }, [user, loading, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
};
