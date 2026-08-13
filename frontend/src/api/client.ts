import type {
  LoginResponse,
  StartFarmingResponse,
  CsvUploadResponse,
  KeywordSet,
  HealthResponse,
  DetailedHealthResponse,
  FarmingAnalytics,
  KeepAliveStatus,
  StorageState,
  ProxyMapEntry,
  GmailAccount,
  ProxySettings,
} from '../types'

// Boş (relative) → same-origin. Prod'da nginx, dev'de Vite /api ve /ws'i backend'e
// proxy'ler; böylece httpOnly cookie sorunsuz gönderilir.
const API_BASE = import.meta.env.VITE_API_URL ?? ''
const AUTH_FLAG = 'iu_authed'  // sadece UI durumu — GİZLİ DEĞİL (token değil)

if (
  import.meta.env.PROD &&
  API_BASE.startsWith('http://') &&
  !/localhost|127\.0\.0\.1/.test(API_BASE)
) {
  console.error('[GÜVENLİK] VITE_API_URL production ortamında HTTPS olmalıdır.')
}

// Token JS'e HİÇ verilmez — auth yalnızca httpOnly cookie ile taşınır
// (XSS token'ı okuyamaz). localStorage'da yalnızca gizli-olmayan UI bayrağı tutulur.
let onAuthExpired: (() => void) | null = null

export function setToken(_t?: string) {
  // Token saklanmaz; sunucu httpOnly cookie'yi zaten set etti. Sadece UI durumu.
  localStorage.setItem(AUTH_FLAG, '1')
}

export function clearToken() {
  localStorage.removeItem(AUTH_FLAG)
}

export function getToken(): string | null {
  // Cookie httpOnly olduğu için JS token'a erişemez (kasıtlı). WS same-origin
  // cookie ile doğrulanır; bu yalnızca eski çağrı yerleriyle uyum içindir.
  return null
}

export function isAuthed(): boolean {
  return localStorage.getItem(AUTH_FLAG) === '1'
}

export function setAuthExpiredHandler(handler: () => void) {
  onAuthExpired = handler
}

function authHeaders(base: Record<string, string> = {}): Record<string, string> {
  // Authorization header yok — kimlik httpOnly cookie ile (credentials: 'include').
  return { ...base }
}

function handleUnauthorized() {
  clearToken()
  onAuthExpired?.()
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = authHeaders({
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  })

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers, credentials: 'include' })

  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Oturum süresi doldu, tekrar giriş yapın')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// Authorization header / cookie ile dosya indirir → token URL'de ifşa olmaz.
async function download(path: string, filename: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders(), credentials: 'include' })
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Oturum süresi doldu')
  }
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({ detail: 'İndirme başarısız' }))
    throw new Error(errBody.detail || 'İndirme başarısız')
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const api = {
  login: (username: string, password: string) =>
    request<LoginResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  // httpOnly cookie geçerli mi? (refresh sonrası oturum bootstrap için)
  checkAuth: async (): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
        headers: authHeaders(),
        credentials: 'include',
      })
      return res.ok
    } catch {
      return false
    }
  },

  // Oturumu gerçekten sonlandıran şey sunucunun httpOnly cookie'yi temizlemesidir;
  // başarısız olursa THROW eder ki UI state'i erkenden temizlenmesin (aksi halde
  // cookie canlıyken checkAuth bir sonraki mount'ta yeniden giriş yapardı).
  logout: async (): Promise<void> => {
    const res = await fetch(`${API_BASE}/api/v1/auth/logout`, {
      method: 'POST',
      headers: authHeaders(),
      credentials: 'include',
    })
    if (!res.ok) throw new Error('Çıkış başarısız — tekrar deneyin')
  },

  uploadCsv: async (file: File): Promise<CsvUploadResponse> => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${API_BASE}/api/v1/upload-csv`, {
      method: 'POST',
      body: form,
      headers: authHeaders(),
      credentials: 'include',
    })
    if (res.status === 401) {
      handleUnauthorized()
      throw new Error('Oturum süresi doldu')
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: 'CSV yüklemesi başarısız' }))
      throw new Error(body.detail || 'CSV yüklemesi başarısız')
    }
    return res.json()
  },

  startFarming: (data: {
    email: string; count: number; lifespan_days: number;
    sector: string; mode: string; keywords?: string[]
  }) =>
    request<StartFarmingResponse>('/api/v1/generate-farm', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Havuzdaki TÜM hesapları tek batch'te işle — her hesap için count_per_account profil.
  startFarmingAll: (data: {
    count_per_account: number; lifespan_days: number; sector: string; mode: string; keywords?: string[]
  }) =>
    request<StartFarmingResponse>('/api/v1/generate-farm-all', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getFarmingStatus: (batchId: string) =>
    request<{ status: string; completed: number; failed: number }>(`/api/v1/farming/status/${batchId}`),

  stopFarming: (batchId: string) =>
    request<{ batch_id: string; status: string }>(`/api/v1/farming/stop/${batchId}`, { method: 'POST' }),

  getKeywords: (sector: string) =>
    request<KeywordSet>(`/api/v1/keywords/${encodeURIComponent(sector)}`),

  setKeywords: (sector: string, keywords: string[]) =>
    request<KeywordSet>('/api/v1/keywords/custom', {
      method: 'PUT',
      body: JSON.stringify({ sector, keywords }),
    }),

  inspectCookie: (email: string, profileIndex: number) =>
    request<StorageState>(`/api/v1/session/inspector?email=${encodeURIComponent(email)}&profile_index=${profileIndex}`),


  getProxyMap: (email: string) =>
    request<ProxyMapEntry[]>(`/api/v1/proxy-map?email=${encodeURIComponent(email)}`),

  getHealth: () => request<HealthResponse>('/health'),
  getHealthDetailed: () => request<DetailedHealthResponse>('/health/detailed'),

  getFarmingAnalytics: (batchId: string) =>
    request<FarmingAnalytics>(`/api/v1/farming/analytics/${batchId}`),

  toggleKeepAlive: () =>
    request<KeepAliveStatus>('/api/v1/sessions/keep-alive/toggle', { method: 'POST' }),

  getKeepAliveStatus: () =>
    request<KeepAliveStatus>('/api/v1/sessions/keep-alive/status'),

  pingKeepAliveNow: () =>
    request<{ started: boolean; detail: string }>('/api/v1/sessions/keep-alive/ping-now', { method: 'POST' }),

  // Kullanıcı ayarları — Telegram bildirimleri + şifre değiştirme
  getTelegram: () =>
    request<import('../types').TelegramSettings>('/api/v1/settings/telegram'),
  setTelegram: (body: { bot_token: string; chat_id: string; enabled: boolean }) =>
    request<import('../types').TelegramSettings>('/api/v1/settings/telegram', { method: 'PUT', body: JSON.stringify(body) }),
  testTelegram: () =>
    request<{ ok: boolean; detail: string }>('/api/v1/settings/telegram/test', { method: 'POST' }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    request<{ status: string; detail: string }>('/api/v1/auth/change-password', { method: 'POST', body: JSON.stringify(body) }),

  downloadManifest: (email: string) =>
    download(`/api/v1/export/manifest?email=${encodeURIComponent(email)}`, 'batch_manifest.json'),
  downloadZip: (email: string) =>
    download(`/api/v1/export/zip?email=${encodeURIComponent(email)}`, `${email.replace(/[^a-z0-9]/gi, '_')}_profiles.zip`),
  // Tek profilin çerezlerini GoLogin-uyumlu JSON olarak indir.
  downloadGologin: (email: string, profileIndex: number) =>
    download(`/api/v1/export/gologin?email=${encodeURIComponent(email)}&profile_index=${profileIndex}`,
      `${email.replace(/[^a-z0-9]/gi, '_')}_p${profileIndex}_gologin.json`),
  // Tek profilin çerezlerini OzyClick/Playwright-uyumlu JSON olarak indir.
  downloadAdswhite: (email: string, profileIndex: number) =>
    download(`/api/v1/export/adswhite?email=${encodeURIComponent(email)}&profile_index=${profileIndex}`,
      `${email.replace(/[^a-z0-9]/gi, '_')}_p${profileIndex}_ozyclick.json`),
  // Havuzdaki TOPLAM üretilmiş profil sayısı + hesap kırılımı.
  getExportStats: () =>
    request<{ total_profiles: number; accounts: number; breakdown: { account: string; profiles: number }[] }>('/api/v1/export/stats'),
  // TÜM hesapların TÜM profillerini tek ZIP indir (adswhite/gologin/universal/netscape/raw).
  downloadAll: (format: 'adswhite' | 'gologin' | 'universal' | 'netscape' | 'raw') =>
    download(`/api/v1/export/all?format=${format}`, `havuz_tumu_${format === 'adswhite' ? 'ozyclick' : format}.zip`),
  // Tek profili seçilen formatta indir.
  downloadSingle: (email: string, profileIndex: number, format: 'adswhite' | 'gologin' | 'universal' | 'netscape' | 'raw') =>
    download(`/api/v1/export/single?email=${encodeURIComponent(email)}&profile_index=${profileIndex}&format=${format}`,
      `${email.replace(/[^a-z0-9]/gi, '_')}_p${profileIndex}_${format === 'adswhite' ? 'ozyclick' : format}.${format === 'netscape' ? 'txt' : 'json'}`),
  // CANLI KONTROL: çerez hâlâ aktif mi (doğduğu fingerprint+proxy ile Google'a sokar).
  checkLive: (email: string, profileIndex: number) =>
    request<{ alive: boolean | null; skipped?: boolean; url: string; detail: string }>(
      `/api/v1/session/check-live?email=${encodeURIComponent(email)}&profile_index=${profileIndex}`),
  // Havuzdaki tüm üretilmiş çıktıları sil.
  purgeAllOutputs: () =>
    request<{ deleted_accounts: number; deleted_profiles: number }>('/api/v1/export/purge-all', { method: 'POST' }),

  getAccounts: () =>
    request<{ accounts: GmailAccount[] }>('/api/v1/accounts'),
  // Cihaz-onaylı 2FA (otomatikleşmez) hesaplar + hesap başına bugünkü üretim sayısı.
  getAccountFlags: () =>
    request<{ device_prompt: string[]; daily: Record<string, number>; daily_limit: number }>('/api/v1/accounts/flags'),

  // Seçili hesabın üretilmiş profillerini sil.
  purgeAccount: (email: string) =>
    request<{ deleted_files: number }>(`/api/v1/export/purge?email=${encodeURIComponent(email)}`, { method: 'POST' }),

  // Tüm batch geçmişini sil.
  clearBatchHistory: () =>
    request<{ deleted: number }>('/api/v1/farming/history/clear', { method: 'POST' }),

  // Canlı log geçmişini (sunucu buffer) temizle.
  clearLogs: () =>
    request<{ cleared: boolean }>('/api/v1/farming/logs/clear', { method: 'POST' }),

  getProxySettings: () =>
    request<ProxySettings>('/api/v1/proxy-settings'),
  setProxySettings: (patch: Partial<{
    provider: 'csv' | 'scrapingbee' | 'list'; country: string; render_js: boolean
    quality: 'classic' | 'premium' | 'stealth'
    add_api_keys: string[]; set_api_keys: string[]; remove_api_key_index: number; active_index: number
    add_proxies: string[]; set_proxies: string[]; remove_proxy_index: number
  }>) =>
    request<ProxySettings>('/api/v1/proxy-settings', { method: 'PUT', body: JSON.stringify(patch) }),
  rotateProxyKey: () =>
    request<ProxySettings>('/api/v1/proxy-settings/rotate', { method: 'POST' }),

  // Proxy canlılık testi (çıkış IP + gecikme). index verilirse sadece o, yoksa hepsi.
  testProxies: (index?: number) =>
    request<{
      provider: string
      results: { index: number; proxy: string; alive: boolean; latency_ms: number; exit_ip: string; error: string }[]
    }>('/api/v1/proxy-settings/test', { method: 'POST', body: JSON.stringify(index === undefined ? {} : { index }) }),

  // Çalışma modu (DRY_RUN aç/kapa)
  getRunMode: () => request<{ dry_run: boolean }>('/api/v1/run-mode'),
  setRunMode: (dry_run: boolean) =>
    request<{ dry_run: boolean }>('/api/v1/run-mode', { method: 'PUT', body: JSON.stringify({ dry_run }) }),

  // Hedef siteler (login sonrası gezilip gerçek çerezleri toplanır)
  getTargetSites: () => request<{ sites: string[]; defaults: string[] }>('/api/v1/target-sites'),
  setTargetSites: (sites: string[]) =>
    request<{ sites: string[] }>('/api/v1/target-sites', { method: 'PUT', body: JSON.stringify({ sites }) }),

  // Manuel hesap ekle / sil (txt bağımlılığı yok).
  addAccount: (acc: { email: string; password: string; totp_secret?: string; proxy_ip?: string; recovery_email?: string }) =>
    request<{ message: string; accounts: GmailAccount[] }>('/api/v1/accounts', {
      method: 'POST', body: JSON.stringify(acc),
    }),
  // Toplu ekle — yapıştırılan metin (her satır: email|password|totp|recovery|proxy).
  addAccountsBulk: (text: string) =>
    request<{ message: string; accounts: GmailAccount[]; added: number }>('/api/v1/accounts/bulk', {
      method: 'POST', body: JSON.stringify({ text }),
    }),
  removeAccount: (email: string) =>
    request<{ accounts: GmailAccount[] }>(`/api/v1/accounts?email=${encodeURIComponent(email)}`, { method: 'DELETE' }),
  // Tek hesabın gizli alanlarını göster (admin, açık talep).
  revealAccount: (email: string) =>
    request<{ email: string; password: string; totp_secret: string; proxy_ip: string }>(
      `/api/v1/accounts/reveal?email=${encodeURIComponent(email)}`),
  getActiveBatch: () =>
    request<{
      batch_id: string | null
      account_email?: string
      status?: string
      total?: number
      completed?: number
      failed?: number
    }>('/api/v1/farming/active'),
}

export function getWsUrl(): string {
  const override = import.meta.env.VITE_WS_URL
  if (override) return `${override}/ws/farming-logs`
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/farming-logs`
}
