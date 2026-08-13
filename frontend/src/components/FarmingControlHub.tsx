import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Play, Square, Zap, Shield, Rocket, RefreshCw, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import type { FarmingLogEntry } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

const MODES = [
  { id: 'SAFE', label: 'Safe', icon: Shield, desc: 'yavaş · aynı anda 3 tarayıcı' },
  { id: 'FAST', label: 'Fast', icon: Zap, desc: 'dengeli · aynı anda 10 tarayıcı' },
  // NOT: Turbo nominal 80 worker ama koda gömülü clamp aynı anda tarayıcıyı browser_pool_size
  // (=10) ile sınırlar → gerçekte 10 tarayıcı, master-login+klon ile daha hızlı (ayrı 2FA yok).
  { id: 'TURBO', label: 'Turbo', icon: Rocket, desc: 'en hızlı · master-login+klon · yine 10 tarayıcı' },
] as const

// İdeal: hesap başına düşük tut (Google flag'lemesin). Tek-hesapta toplam, çoklu-hesapta
// HER hesap için üretilecek profil sayısıdır. "1 mailden ~40" pratik üst sınır.
const COUNT_OPTIONS = [20, 40, 100, 250] as const
const MIN_COUNT = 20          // minimum profil sayısı (kullanıcı isteği)
const RECOMMENDED_MAX = 40    // bunun üstü İZİNLİ ama risk uyarısı gösterilir (Google flag/oran)

interface Props {
  email: string
  sector: string
  keywords: string[]
  logs: FarmingLogEntry[]
  wsConnected: boolean
  activeBatchId: string | null
  batchStatus: string | null
  onBatchStarted: (batchId: string) => void
  onBatchStatusChange: (status: string | null) => void
  onClearLogs?: () => void
}

const ACTIVE_STATUSES = new Set(['PENDING', 'FARMING'])

export default function FarmingControlHub({
  email, sector, keywords, logs, wsConnected, activeBatchId, batchStatus, onBatchStarted, onBatchStatusChange, onClearLogs,
}: Props) {
  const [mode, setMode] = useState('FAST')   // ideal: 10 paralel worker (8 vCPU'ya uygun)
  const [count, setCount] = useState(MIN_COUNT)   // min 20; üstü serbest (max kullanıcı belirler)
  const [lifespan, setLifespan] = useState(5)

  const isBatchActive = !!activeBatchId && ACTIVE_STATUSES.has(batchStatus || '')

  // Aktif batch varken durumunu takip et
  useQuery({
    queryKey: ['farming-status', activeBatchId],
    queryFn: async () => {
      const data = await api.getFarmingStatus(activeBatchId!)
      if (data.status && data.status !== batchStatus) {
        onBatchStatusChange(data.status)
      }
      return data
    },
    enabled: isBatchActive,
    refetchInterval: 3_000,
  })

  const startMutation = useMutation({
    mutationFn: () => api.startFarming({ email, count, lifespan_days: lifespan, sector, mode, keywords }),
    onSuccess: (data) => {
      toast.success(data.message)
      onBatchStarted(data.batch_id)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const startAllMutation = useMutation({
    mutationFn: () => api.startFarmingAll({
      count_per_account: count, lifespan_days: lifespan, sector, mode, keywords,
    }),
    onSuccess: (data) => {
      toast.success(data.message)
      onBatchStarted(data.batch_id)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const stopMutation = useMutation({
    mutationFn: () => api.stopFarming(activeBatchId!),
    onSuccess: () => {
      toast.success('Farming durduruldu')
      onBatchStatusChange('STOPPED')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const canStart = !!email && !startMutation.isPending && !isBatchActive
  const statusLabel = batchStatus === 'COMPLETED' ? '✓ Tamamlandı' :
    batchStatus === 'COMPLETED_PARTIAL' ? '⚠ Kısmi Tamamlandı' :
    batchStatus === 'FAILED' ? '✗ Başarısız' :
    batchStatus === 'STOPPED' ? '■ Durduruldu' :
    batchStatus === 'FARMING' ? '▶ Üretim devam ediyor...' :
    batchStatus === 'PENDING' ? '◷ Başlıyor...' : null

  return (
    <GlassCard className="space-y-4">
      <PanelHeader
        icon={Play}
        title="Farming Control Hub"
        actions={statusLabel ? (
          <span className={`text-[10px] font-mono ${
            batchStatus === 'FARMING' || batchStatus === 'PENDING' ? 'text-iuGold animate-pulse' :
            batchStatus === 'COMPLETED' ? 'text-emerald-400' :
            batchStatus === 'FAILED' ? 'text-red-400' : 'text-slate-500'
          }`}>
            {statusLabel}
          </span>
        ) : null}
      />

      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        {MODES.map(m => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            aria-pressed={mode === m.id}
            className={`p-2.5 sm:p-3 rounded-xl border text-left transition-all ${
              mode === m.id
                ? 'border-iuGold bg-iuGold/10 text-iuGold'
                : 'border-iuBorder hover:border-iuBorder/80 text-slate-400'
            }`}
          >
            <m.icon className="w-4 h-4 sm:w-5 sm:h-5 mb-1" aria-hidden="true" />
            <p className="text-xs sm:text-sm font-medium">{m.label}</p>
            <p className="text-[10px] text-slate-500 hidden sm:block">{m.desc}</p>
          </button>
        ))}
      </div>

      <div className="flex flex-col sm:flex-row gap-3 sm:gap-4 sm:items-end">
        <div className="flex-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Profil Sayısı (min {MIN_COUNT}, üstü serbest)</label>
          <div className="flex gap-1.5 mt-1" role="radiogroup" aria-label="Profil sayısı">
            {COUNT_OPTIONS.map(c => (
              <button
                key={c}
                onClick={() => setCount(c)}
                role="radio"
                aria-checked={count === c}
                className={`flex-1 py-1.5 rounded-lg text-xs transition-all ${
                  count === c ? 'bg-iuGold text-iuNavy font-semibold' : 'bg-iuNavy/50 text-slate-400 hover:bg-iuNavy/80'
                }`}
              >
                {c >= 1000 ? `${c / 1000}K` : c}
              </button>
            ))}
            {/* Serbest sayı: max'ı kullanıcı belirler; 20 altı otomatik 20'ye çekilir */}
            <input
              type="number"
              min={MIN_COUNT}
              value={count}
              onChange={e => setCount(Math.max(MIN_COUNT, Number(e.target.value) || MIN_COUNT))}
              aria-label="Özel profil sayısı"
              className="w-20 py-1.5 px-2 rounded-lg text-xs text-center bg-iuNavy/50 text-slate-200 border border-iuBorder focus:border-iuGold focus:outline-none"
            />
          </div>
          {count > RECOMMENDED_MAX && (
            <p className="mt-1 text-[10px] text-amber-400 flex items-start gap-1">
              <span>⚠️</span>
              <span>{count} profil — önerilenin ({RECOMMENDED_MAX}) üstünde. Google flag/oran-limit riski artar (özellikle tek hesapta üst üste). İzinli, dikkatli devam et.</span>
            </p>
          )}
        </div>
        <div>
          <label htmlFor="lifespan-select" className="text-[10px] text-slate-500 uppercase tracking-wider">
            Ömür
          </label>
          <select
            id="lifespan-select"
            value={lifespan}
            onChange={e => setLifespan(Number(e.target.value))}
            className="mt-1 block bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:border-iuGold focus:outline-none"
          >
            <option value={3}>3 Gün</option>
            <option value={4}>4 Gün</option>
            <option value={5}>5 Gün</option>
          </select>
        </div>
      </div>

      <div className="flex gap-3">
        <button
          onClick={() => startMutation.mutate()}
          disabled={!canStart}
          className="flex-1 py-2.5 rounded-xl btn-gold font-semibold text-sm disabled:opacity-40 flex items-center justify-center gap-2"
        >
          {isBatchActive ? (
            <RefreshCw className="w-4 h-4 animate-spin" aria-hidden="true" />
          ) : (
            <Play className="w-4 h-4" aria-hidden="true" />
          )}
          {startMutation.isPending ? 'Başlatılıyor...' :
           isBatchActive ? 'Üretim devam ediyor...' :
           'Farming Başlat'}
        </button>
        {isBatchActive && (
          <button
            onClick={() => stopMutation.mutate()}
            disabled={stopMutation.isPending}
            aria-label="Farming durdur"
            className="px-4 py-2.5 rounded-xl bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 disabled:opacity-40 transition-all"
          >
            <Square className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Çoklu-hesap: tek maile yığmak yerine havuzdaki TÜM hesaplara dağıt (paralel, hızlı) */}
      <button
        onClick={() => startAllMutation.mutate()}
        disabled={isBatchActive || startAllMutation.isPending}
        title="Havuzdaki tüm hesaplar için (her hesap × seçili profil sayısı) — farklı hesaplar paralel, TOTP çakışması yok"
        className="w-full py-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 hover:bg-emerald-500/20 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-sm font-medium"
      >
        <Play className="w-4 h-4" aria-hidden="true" />
        {startAllMutation.isPending ? 'Başlatılıyor...' : `Tüm Havuzu Üret · her hesap × ${count}`}
      </button>

      <div
        className="bg-black/40 rounded-xl p-3 h-36 sm:h-40 overflow-y-auto font-mono text-[11px] leading-relaxed"
        role="log"
        aria-label="Farming logları"
        aria-live="polite"
      >
        <div className="flex items-center gap-2 mb-2">
          <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-emerald-400 pulse-dot' : 'bg-red-500'}`} />
          <span className="text-slate-600 text-[10px]">
            {wsConnected ? 'Canlı bağlantı' : 'Bağlantı bekleniyor...'}
          </span>
          {onClearLogs && logs.length > 0 && (
            <button
              onClick={onClearLogs}
              aria-label="Logları temizle"
              title="Logları temizle"
              className="ml-auto p-0.5 rounded text-slate-600 hover:text-red-400 transition-colors"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          )}
        </div>
        {logs.length === 0 && (
          <p className="text-slate-600">Farming başladığında loglar burada görünecek...</p>
        )}
        {/* PERF: yalnız son 40 log render edilir (kap kaydırılabilir) → Fast/Turbo'da 200 DOM
            node'u her flush'ta yeniden çizmek kasmaya yol açıyordu. */}
        {logs.slice(-40).map((log, i) => (
          <p key={i} className={
            log.level === 'ERROR' ? 'text-red-400' :
            log.level === 'WARNING' ? 'text-amber-400' : 'text-emerald-400'
          }>
            [{new Date(log.timestamp * 1000).toLocaleTimeString('tr-TR')}] {log.message}
          </p>
        ))}
      </div>
    </GlassCard>
  )
}
