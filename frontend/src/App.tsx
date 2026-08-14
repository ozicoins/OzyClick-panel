import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { LayoutDashboard, Play, Cookie, Settings, X } from 'lucide-react'
import { api, setToken, isAuthed, clearToken, setAuthExpiredHandler } from './api/client'
import { useFarmingLogs } from './hooks/useFarmingLogs'
import type { GmailAccount } from './types'

import ErrorBoundary from './components/ErrorBoundary'
import OzyLogo from './components/ui/OzyLogo'
import Header from './components/Header'
import KeywordManager from './components/KeywordManager'
import FarmingControlHub from './components/FarmingControlHub'
import ExporterPanel from './components/ExporterPanel'
import PoolHealthCard from './components/PoolHealthCard'
import FailedAccountsCard from './components/FailedAccountsCard'
import RejectedIpCard from './components/RejectedIpCard'
import WorkerMonitor from './components/WorkerMonitor'
import GmailPoolManager from './components/GmailPoolManager'
import SessionKeepAlive from './components/SessionKeepAlive'
import BatchAnalytics from './components/BatchAnalytics'
import SystemStatus from './components/SystemStatus'
import ProxySettings from './components/ProxySettings'
import RunModeSettings from './components/RunModeSettings'
import UserSettings from './components/UserSettings'
import AutomationSettings from './components/AutomationSettings'
import TargetSitesManager from './components/TargetSitesManager'

type TabId = 'home' | 'farming' | 'outputs' | 'settings'

// Terminal batch durumları — bir kez ulaşınca poll ile geri açılmamalı.
const TERMINAL_STATUSES = ['STOPPED', 'COMPLETED', 'COMPLETED_PARTIAL', 'FAILED']

const TABS: { id: TabId; label: string; icon: typeof LayoutDashboard }[] = [
  { id: 'home', label: 'Genel Bakış', icon: LayoutDashboard },
  { id: 'farming', label: 'Üretim', icon: Play },
  { id: 'outputs', label: 'Çıktılar', icon: Cookie },
  { id: 'settings', label: 'Ayarlar', icon: Settings },
]

function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      setError('Kullanıcı adı ve şifre gerekli')
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await api.login(username, password)
      setToken(data.access_token)
      onLogin()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Giriş başarısız')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 above-texture">
      <div className="glass-card gold-glow above-texture animate-fade-up p-6 sm:p-8 w-full max-w-sm space-y-6">
        <div className="text-center space-y-3">
          <span className="inline-grid place-items-center w-14 h-14 rounded-2xl bg-gradient-to-br from-iuGold/30 via-iuGold/10 to-transparent border border-iuGold/25 text-iuGold shadow-gold">
            <OzyLogo size={34} />
          </span>
          <div>
            <h1 className="heading-font text-xl sm:text-2xl font-extrabold text-gradient-gold">OzyClick</h1>
            <p className="text-xs text-slate-400 tracking-[0.2em] uppercase mt-1 mono-font">Cookie Generator · hit-bot</p>
          </div>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="login-user" className="sr-only">Kullanıcı adı</label>
            <input
              id="login-user"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="Kullanıcı adı"
              autoComplete="username"
              className="w-full bg-iuNavy/50 border border-iuBorder rounded-xl px-4 py-3 text-sm text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none focus:ring-1 focus:ring-iuGold/30"
            />
          </div>
          <div>
            <label htmlFor="login-pass" className="sr-only">Şifre</label>
            <input
              id="login-pass"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Şifre"
              autoComplete="current-password"
              className="w-full bg-iuNavy/50 border border-iuBorder rounded-xl px-4 py-3 text-sm text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none focus:ring-1 focus:ring-iuGold/30"
            />
          </div>
          {error && (
            <p role="alert" className="text-xs text-red-400">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl btn-gold font-semibold text-sm disabled:opacity-50"
          >
            {loading ? 'Giriş yapılıyor...' : 'Giriş Yap'}
          </button>
        </form>
      </div>
    </div>
  )
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(isAuthed())
  const [tab, setTab] = useState<TabId>('home')
  const [showSettings, setShowSettings] = useState(false)   // header ⚙️ → Kullanıcı Ayarları modalı
  const [accounts, setAccounts] = useState<GmailAccount[]>([])
  const [activeEmail, setActiveEmail] = useState('')
  const [sector, setSector] = useState('Alışveriş (E-Ticaret Harmanı)')
  const [keywords, setKeywords] = useState<string[]>([])
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)
  const [batchStatus, setBatchStatus] = useState<string | null>(null)
  const { logs, connected, clearLogs } = useFarmingLogs(authenticated)

  // Poll'dan gelen durumu uygula ama TERMINAL durumu (STOPPED/COMPLETED/...) non-terminal
  // (FARMING) ile ASLA ezme → "Durdur"dan sonra geç gelen poll batch'i geri açmasın.
  const applyPolledStatus = (s: string | null) =>
    setBatchStatus(prev =>
      prev && s !== null && TERMINAL_STATUSES.includes(prev) && !TERMINAL_STATUSES.includes(s) ? prev : s)

  // App seviyesinde batch durumu poll'u → hangi sekmede olursak olalım biten batch
  // "tamamlandı"ya döner (FarmingControlHub farming sekmesinde mount olmasa bile).
  useQuery({
    queryKey: ['app-batch-status', activeBatchId],
    queryFn: async () => {
      const d = await api.getFarmingStatus(activeBatchId!)
      if (d.status && d.status !== batchStatus) applyPolledStatus(d.status)
      return d
    },
    enabled: !!activeBatchId && ['PENDING', 'FARMING'].includes(batchStatus || ''),
    refetchInterval: 3000,
  })

  const clearSensitiveState = () => {
    setAccounts([])
    setActiveEmail('')
    setActiveBatchId(null)
    setBatchStatus(null)
    clearLogs()
  }

  const handleLogout = async () => {
    try {
      await api.logout()
    } catch {
      toast.error('Çıkış yapılamadı, tekrar deneyin')
      return
    }
    clearToken()
    clearSensitiveState()
    setAuthenticated(false)
  }

  useEffect(() => {
    setAuthExpiredHandler(() => {
      clearSensitiveState()
      setAuthenticated(false)
    })
    api.checkAuth().then((ok) => {
      setAuthenticated(ok)
      if (ok) {
        api.getAccounts().then((res) => {
          if (res.accounts && res.accounts.length > 0) {
            setAccounts(res.accounts as GmailAccount[])
            setActiveEmail((prev) => prev || res.accounts[0].email)
          }
        }).catch(() => {})
        api.getActiveBatch().then((batchRes) => {
          if (batchRes.batch_id) {
            setActiveBatchId(batchRes.batch_id)
            setBatchStatus(batchRes.status || null)
            if (batchRes.account_email) setActiveEmail(batchRes.account_email)
          }
        }).catch(() => {})
      } else {
        clearSensitiveState()
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated])

  const handleBatchStarted = (batchId: string) => {
    setActiveBatchId(batchId)
    setBatchStatus('FARMING')
    setTab('home')  // batch başlayınca genel bakışta ilerleme görünsün
  }

  // Logları hem istemcide hem sunucu buffer'ında temizle (yenilemede geri gelmesin).
  const handleClearLogs = () => {
    clearLogs()
    api.clearLogs().catch(() => {})
  }

  if (!authenticated) {
    return <LoginScreen onLogin={() => setAuthenticated(true)} />
  }

  return (
    <>
      <div className="min-h-screen p-3 sm:p-4 space-y-4 max-w-[1600px] mx-auto above-texture">
        <ErrorBoundary fallbackTitle="Header yüklenemedi">
          <Header onLogout={handleLogout} onOpenSettings={() => setShowSettings(true)} />
        </ErrorBoundary>

        {/* Sekme çubuğu — yapışkan, camsı, aktif sekmede gold gradyan + parıltı */}
        <nav
          className="sticky top-2 z-20 flex gap-1.5 p-1.5 rounded-2xl bg-iuCard/70 backdrop-blur-xl border border-iuBorder/80 shadow-[0_10px_30px_-14px_rgba(0,0,0,0.7)] overflow-x-auto animate-fade-in"
          role="tablist"
          aria-label="Bölümler"
        >
          {TABS.map(t => {
            const active = tab === t.id
            return (
              <button
                key={t.id}
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t.id)}
                className={`relative flex items-center gap-2 px-4 py-2 rounded-xl text-sm whitespace-nowrap transition-all duration-200 ${
                  active
                    ? 'btn-gold font-semibold'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-white/[0.05]'
                }`}
              >
                <t.icon className="w-4 h-4" aria-hidden="true" />
                {t.label}
              </button>
            )
          })}
        </nav>

        {/* GENEL BAKIŞ — sadece çalışma bilgileri (tablolar/özet) */}
        {tab === 'home' && (
          <div className="space-y-4">
            <ErrorBoundary>
              <BatchAnalytics
                activeBatchId={activeBatchId}
                batchStatus={batchStatus}
                onCleared={() => { setActiveBatchId(null); setBatchStatus(null) }}
              />
            </ErrorBoundary>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <ErrorBoundary>
                <WorkerMonitor logs={logs} activeBatchId={activeBatchId} onClear={handleClearLogs} />
              </ErrorBoundary>
              <ErrorBoundary>
                <SystemStatus />
              </ErrorBoundary>
            </div>
          </div>
        )}

        {/* ÜRETİM — hesaplar, kelimeler, farming kontrol */}
        {tab === 'farming' && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="space-y-4">
                <ErrorBoundary>
                  <GmailPoolManager
                    accounts={accounts}
                    activeEmail={activeEmail}
                    onSelectEmail={setActiveEmail}
                    onAccountsChanged={(accs) => {
                      setAccounts(accs)
                      // Aktif hesap listede kalmadıysa: hesap varsa ilkine geç, HİÇ kalmadıysa
                      // temizle (aksi halde silinen hesabı sorgulamaya devam ediliyordu).
                      if (!accs.some(a => a.email === activeEmail)) setActiveEmail(accs[0]?.email ?? '')
                    }}
                  />
                </ErrorBoundary>
                <ErrorBoundary>
                  <TargetSitesManager />
                </ErrorBoundary>
              </div>
              <div className="lg:col-span-2">
                <ErrorBoundary>
                  <FarmingControlHub
                    email={activeEmail}
                    sector={sector}
                    keywords={keywords}
                    logs={logs}
                    wsConnected={connected}
                    activeBatchId={activeBatchId}
                    batchStatus={batchStatus}
                    onBatchStarted={handleBatchStarted}
                    onBatchStatusChange={applyPolledStatus}
                    onClearLogs={handleClearLogs}
                  />
                </ErrorBoundary>
              </div>
            </div>
            {/* Kelime paneli tam genişlik → çipler yatay yayılır, boşluk kalmaz */}
            <ErrorBoundary>
              <KeywordManager
                selectedSector={sector}
                onSectorChange={setSector}
                keywords={keywords}
                onKeywordsChange={setKeywords}
              />
            </ErrorBoundary>
          </div>
        )}

        {/* ÇIKTILAR — havuz sağlığı (toplu canlılık) + toplu indirme + Drive yedekleri.
            items-stretch (varsayılan) → iki kart eşit yükseklikte, alt kenarları hizalı. */}
        {tab === 'outputs' && (
          <div className="max-w-4xl mx-auto space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <ErrorBoundary>
                <PoolHealthCard />
              </ErrorBoundary>
              <ErrorBoundary>
                <ExporterPanel email="" />
              </ErrorBoundary>
            </div>
            {/* Sorunlu hesaplar (2FA ek-doğrulama/parola) — hesabın kendi sorunu, sorun varsa görünür */}
            <ErrorBoundary>
              <FailedAccountsCard />
            </ErrorBoundary>
            {/* IP Reddi (Google REDDETTİ) — proxy/IP sorunu, hesap suçlanmaz; reddi varsa görünür */}
            <ErrorBoundary>
              <RejectedIpCard />
            </ErrorBoundary>
          </div>
        )}

        {/* AYARLAR — düz 2×2 grid: her satırdaki iki kart eşit yükseklikte (altları hizalı).
            Uzun kartlar (Proxy + Otomasyon) üst satırda, kısalar (Keep-Alive + Çalışma Modu) altta. */}
        {tab === 'settings' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ErrorBoundary>
              <ProxySettings />
            </ErrorBoundary>
            <ErrorBoundary>
              <AutomationSettings />
            </ErrorBoundary>
            <ErrorBoundary>
              <SessionKeepAlive />
            </ErrorBoundary>
            <ErrorBoundary>
              <RunModeSettings />
            </ErrorBoundary>
          </div>
        )}
      </div>

      {/* Kullanıcı Ayarları — header ⚙️ ile açılan modal (her sekmeden erişilir) */}
      {showSettings && (
        <div
          className="fixed inset-0 z-[60] flex items-start sm:items-center justify-center p-4 bg-black/70 backdrop-blur-sm overflow-y-auto"
          onClick={() => setShowSettings(false)}
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-md my-8" onClick={e => e.stopPropagation()}>
            <div className="flex justify-end mb-2">
              <button
                onClick={() => setShowSettings(false)}
                className="p-2 rounded-lg bg-iuNavy/60 border border-iuBorder text-slate-400 hover:text-iuGold transition-colors"
                aria-label="Kapat"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <ErrorBoundary>
              <UserSettings />
            </ErrorBoundary>
          </div>
        </div>
      )}
    </>
  )
}
