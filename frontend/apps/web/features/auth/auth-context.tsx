// React context provider for authentication state and token management.
// 로컬 JWT / Keycloak 두 모드 모두 동일한 흐름(토큰 저장 → /me 조회 → 자동 갱신)으로 동작한다.
"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import {
  login as apiLogin,
  logout as apiLogout,
  refreshToken as apiRefreshToken,
  updateAvatar as apiUpdateAvatar,
  fetchAuthType,
  fetchMe,
  type AuthType,
  type TokenResponse,
  type UserInfo,
} from "./api"

type AuthState = {
  user: UserInfo | null
  accessToken: string | null
  authType: AuthType | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<UserInfo>
  logout: () => Promise<void>
  setAvatar: (avatarPresetId: string | null) => Promise<void>
  applyTokens: (tokens: TokenResponse) => Promise<UserInfo>
}

const AuthContext = createContext<AuthState | null>(null)

const TOKEN_KEY = "argus_tokens"

type StoredTokens = {
  access_token: string
  refresh_token: string
  expires_at: number
}

function saveTokens(tokens: TokenResponse) {
  const data: StoredTokens = {
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token,
    expires_at: Date.now() + tokens.expires_in * 1000,
  }
  sessionStorage.setItem(TOKEN_KEY, JSON.stringify(data))
}

function loadTokens(): StoredTokens | null {
  try {
    const raw = sessionStorage.getItem(TOKEN_KEY)
    if (!raw) return null
    return JSON.parse(raw) as StoredTokens
  } catch {
    return null
  }
}

function clearTokens() {
  sessionStorage.removeItem(TOKEN_KEY)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [authType, setAuthType] = useState<AuthType | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const scheduleRefresh = useCallback(function schedule(tokens: StoredTokens) {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current)
    }
    const msUntilRefresh = tokens.expires_at - Date.now() - 60_000
    if (msUntilRefresh <= 0) return

    refreshTimerRef.current = setTimeout(async () => {
      try {
        const stored = loadTokens()
        if (!stored) return
        const newTokens = await apiRefreshToken(stored.refresh_token)
        saveTokens(newTokens)
        setAccessToken(newTokens.access_token)
        schedule({
          access_token: newTokens.access_token,
          refresh_token: newTokens.refresh_token,
          expires_at: Date.now() + newTokens.expires_in * 1000,
        })
      } catch {
        clearTokens()
        setUser(null)
        setAccessToken(null)
      }
    }, msUntilRefresh)
  }, [])

  useEffect(() => {
    fetchAuthType()
      .then(setAuthType)
      .catch(() => {
        // null 이면 consumer 는 "unknown" 으로 취급한다.
      })
  }, [])

  useEffect(() => {
    async function init() {
      const stored = loadTokens()
      if (!stored) {
        setIsLoading(false)
        return
      }

      if (stored.expires_at < Date.now() + 10_000) {
        try {
          const newTokens = await apiRefreshToken(stored.refresh_token)
          saveTokens(newTokens)
          const userInfo = await fetchMe(newTokens.access_token)
          setAccessToken(newTokens.access_token)
          setUser(userInfo)
          scheduleRefresh({
            access_token: newTokens.access_token,
            refresh_token: newTokens.refresh_token,
            expires_at: Date.now() + newTokens.expires_in * 1000,
          })
        } catch {
          clearTokens()
        }
      } else {
        try {
          const userInfo = await fetchMe(stored.access_token)
          setAccessToken(stored.access_token)
          setUser(userInfo)
          scheduleRefresh(stored)
        } catch {
          clearTokens()
        }
      }
      setIsLoading(false)
    }

    init()

    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current)
      }
    }
  }, [scheduleRefresh])

  const establishSession = useCallback(
    async (tokens: TokenResponse): Promise<UserInfo> => {
      saveTokens(tokens)
      const userInfo = await fetchMe(tokens.access_token)
      setAccessToken(tokens.access_token)
      setUser(userInfo)
      scheduleRefresh({
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
        expires_at: Date.now() + tokens.expires_in * 1000,
      })
      return userInfo
    },
    [scheduleRefresh]
  )

  const login = useCallback(
    async (username: string, password: string) => {
      const tokens = await apiLogin(username, password)
      return establishSession(tokens)
    },
    [establishSession]
  )

  const applyTokens = useCallback(
    (tokens: TokenResponse) => establishSession(tokens),
    [establishSession]
  )

  const logout = useCallback(async () => {
    const stored = loadTokens()
    if (stored) {
      await apiLogout(stored.refresh_token).catch(() => {})
    }
    clearTokens()
    setUser(null)
    setAccessToken(null)
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current)
    }
  }, [])

  const setAvatar = useCallback(
    async (avatarPresetId: string | null) => {
      if (!accessToken) {
        throw new Error("Not authenticated")
      }
      const updated = await apiUpdateAvatar(accessToken, avatarPresetId)
      setUser(updated)
    },
    [accessToken]
  )

  const value = useMemo(
    () => ({
      user,
      accessToken,
      authType,
      isAuthenticated: !!user,
      isLoading,
      login,
      logout,
      setAvatar,
      applyTokens,
    }),
    [user, accessToken, authType, isLoading, login, logout, setAvatar, applyTokens]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return ctx
}
