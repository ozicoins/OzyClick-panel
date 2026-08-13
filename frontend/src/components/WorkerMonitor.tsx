import { Activity, Trash2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import type { FarmingLogEntry, FarmingAnalytics } from '../types'
import { api } from '../api/client'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'
import StatBox from './ui/StatBox'
import EmptyState from './ui/EmptyState'

interface Props {
  logs: FarmingLogEntry[]
  activeBatchId?: string | null
  onClear?: () => void
}

export default function WorkerMonitor({ logs, activeBatchId, onClear }: Props) {
  // OTORİTER sayaçlar: aktif batch varsa analytics'ten (BatchAnalytics ile AYNI query → tek fetch,
  // tek gerçek). Böylece "batch 31 / worker 43" uyuşmazlığı biter — worker log'u retry + timeout
  // satırlarıyla ŞİŞİYORDU; başarılı/başarısız artık PROFİL bazında (deneme değil).
  const { data: analytics } = useQuery<FarmingAnalytics>({
    queryKey: ['farming-analytics', activeBatchId],
    queryFn: () => api.getFarmingAnalytics(activeBatchId!),
    enabled: !!activeBatchId,
    refetchInterval: activeBatchId ? 3_000 : false,
  })

  const workerLogs = logs.filter(l => l.message.toLowerCase().includes('worker'))
  const recentWorkers = workerLogs.slice(-10)

  // Aktif batch → OTORİTER (profil bazında). Yoksa (geçmiş/oturum) → log işaretlerinden say (yaklaşık).
  const authoritative = !!activeBatchId && !!analytics
  const successCount = authoritative
    ? (analytics!.completed ?? 0)
    : workerLogs.filter(l => l.message.includes('✓') || l.message.includes('[DRY]')).length
  const failCount = authoritative
    ? (analytics!.failed ?? 0)
    : workerLogs.filter(l => l.message.includes('✗')).length
  const total = authoritative ? (analytics!.total ?? successCount + failCount) : successCount + failCount

  return (
    <GlassCard className="space-y-3">
      <PanelHeader
        icon={Activity}
        title="Worker Monitor"
        actions={onClear && logs.length > 0 ? (
          <button
            onClick={onClear}
            aria-label="Worker loglarını temizle"
            title="Logları temizle"
            className="p-1 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        ) : null}
      />

      <div className="grid grid-cols-3 gap-2">
        <StatBox value={successCount} label="Başarılı" color="emerald" />
        <StatBox value={failCount} label="Başarısız" color="red" />
        <StatBox value={total} label={authoritative ? 'Hedef' : 'Toplam'} color="gold" />
      </div>
      {authoritative && (
        <p className="text-[10px] text-slate-500 text-center">
          Profil bazında (deneme/retry değil) · başarılı + başarısız = işlenen
        </p>
      )}

      <div className="space-y-1 max-h-32 overflow-y-auto" role="log" aria-label="Worker logları">
        {recentWorkers.length === 0 ? (
          <EmptyState message="Worker logu bekleniyor..." />
        ) : (
          recentWorkers.map((log, i) => (
            <div key={i} className={`text-[11px] font-mono px-2 py-1 rounded ${
              log.level === 'ERROR' ? 'bg-red-500/5 text-red-400' : 'bg-emerald-500/5 text-emerald-400'
            }`}>
              {log.message}
            </div>
          ))
        )}
      </div>
    </GlassCard>
  )
}
