// Hassas alanlar (password, totp_secret, recovery_email, phone_number) backend
// tarafından yanıttan çıkarılır ve frontend'e hiç ulaşmaz.
export interface GmailAccount {
  email: string
  proxy_ip: string
  daily_limit: number
  farming_mode: string
}

export interface BatchStatus {
  batch_id: string
  status: 'PENDING' | 'FARMING' | 'COMPLETED' | 'COMPLETED_PARTIAL' | 'FAILED' | 'STOPPED'
  total: number
  completed: number
  failed: number
  mode: string
  started_at: string | null
  completed_at: string | null
}

export interface CookieEntry {
  name: string
  value: string
  domain: string
  path: string
  expires: number
  httpOnly: boolean
  secure: boolean
  sameSite: string
}

export interface StorageState {
  cookies: CookieEntry[]
  origins: { origin: string; localStorage: { name: string; value: string }[] }[]
  device?: string
  user_agent?: string
  proxy_ip?: string
}

export interface ProfileMeta {
  file: string
  sessionId: string
  proxyIp: string
  createdAt: string
  expiresAt: string
  status: string
  cookieCount: number
}

export interface ProxyMapEntry {
  profileFile: string
  assignedProxy: string
  proxyType: string
  location: string
  status: string
}

export interface FarmingLogEntry {
  message: string
  level: string
  timestamp: number
}

export interface HealthResponse {
  status: string
  redis: boolean
  disk_free_gb: number
  disk_percent?: number
  cpu_percent?: number
  cpu_count?: number
  ram_percent?: number
  ram_used_mb?: number
  ram_total_mb?: number
}

export interface DetailedHealthResponse {
  disk: { percent_used: number; free_gb: number; total_gb: number }
  redis: { connected: boolean; used_memory_mb: number; keys: number }
  chrome_pool: { total: number; active: number; zombies: number }
}

export interface KeywordSet {
  sector: string
  keywords: string[]
}

export interface FarmingAnalytics {
  total: number
  completed: number
  failed: number
  active_workers: number
  error_breakdown: { name: string; value: number; color: string }[]
}

export interface KeepAliveStatus {
  active: boolean
  last_ping: string | null
  next_ping: string | null
  success_rate: number
  success_count: number
  total_count: number
  running?: boolean
  processed?: number
}

export interface TelegramSettings {
  enabled: boolean
  bot_token: string
  chat_id: string
  configured?: boolean
}

export type ProxyQuality = 'classic' | 'premium' | 'stealth'

export interface ProxySettings {
  provider: 'csv' | 'scrapingbee' | 'list'
  country: string
  render_js: boolean
  quality: ProxyQuality
  api_key_count: number
  active_index: number
  api_key_previews: string[]
  api_key_configured: boolean
  proxy_count: number
  proxy_previews: string[]
}

export interface LoginResponse {
  access_token: string
}

export interface StartFarmingResponse {
  batch_id: string
  status: string
  message: string
}

export interface CsvUploadResponse {
  accounts: GmailAccount[]
  message: string
}
