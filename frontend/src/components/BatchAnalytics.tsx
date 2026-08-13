import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, CheckCircle2, XCircle, Timer, Trash2 } from 'lucide-react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import type { FarmingAnalytics } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'
import EmptyState from './ui/EmptyState'

interface Props {
  activeBatchId: string | null
  batchStatus?: string | null
  onCleared?: () => void
}

interface ThroughputPoint {
  time: string
  completed: number
  delta: number
}

const ERROR_COLORS: Record<string, string> = {
  TIMEOUT: '#f59e0b',
  CAPTCHA: '#ef4444',
  AUTH_FAIL: '#8b5cf6',
  PROXY_DEAD: '#64748b',
}

export default function BatchAnalytics({ activeBatchId, batchStatus, onCleared }: Props) {
  const queryClient = useQueryClient()
  const [clearing, setClearing] = useState(false)
  const [throughput, setThroughput] = useState<ThroughputPoint[]>([])
  const prevBatchRef = useRef<string | null>(null)
  const prevCompletedRef = useRef(0)
  const initializedRef = useRef(false)

  const isFinished = batchStatus === 'COMPLETED' || batchStatus === 'COMPLETED_PARTIAL' || batchStatus === 'FAILED' || batchStatus === 'STOPPED'

  const { data } = useQuery<FarmingAnalytics>({
    queryKey: ['farming-analytics', activeBatchId],
    queryFn: () => api.getFarmingAnalytics(activeBatchId!),
    enabled: !!activeBatchId,
    refetchInterval: isFinished ? false : 3_000,
  })

  // Batch değiştiğinde throughput'u sıfırla
  useEffect(() => {
    if (activeBatchId !== prevBatchRef.current) {
      setThroughput([])
      prevCompletedRef.current = 0
      prevBatchRef.current = activeBatchId
      initializedRef.current = false
    }
  }, [activeBatchId])

  // İlk veri geldiğinde (sayfa yenilenme dahil) mevcut değerleri grafiğe ekle
  useEffect(() => {
    if (!data || !activeBatchId) return

    const current = data.completed ?? 0
    const currentFailed = data.failed ?? 0

    // İlk yükleme: Server'dan gelen mevcut veriyi grafiğe ilk nokta olarak ekle
    if (!initializedRef.current && current > 0) {
      initializedRef.current = true
      prevCompletedRef.current = current
      const time = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      setThroughput([{ time, completed: current, delta: current }])
      return
    }

    initializedRef.current = true
    const delta = Math.max(0, current - prevCompletedRef.current)
    
    // Delta yoksa (değişiklik yok) gereksiz nokta ekleme
    if (delta === 0 && throughput.length > 0 && isFinished) return
    
    prevCompletedRef.current = current

    const time = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    setThroughput(prev => {
      const next = [...prev, { time, completed: current, delta }]
      return next.length > 60 ? next.slice(-60) : next
    })
  }, [data, activeBatchId])

  const completed = data?.completed ?? 0
  const failed = data?.failed ?? 0
  const total = data?.total ?? 0
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0

  const errorData = (data?.error_breakdown ?? [])
    .filter(e => e.value > 0)
    .map(e => ({ ...e, color: e.color || ERROR_COLORS[e.name] || '#64748b' }))

  const clearHistory = async () => {
    if (clearing) return
    if (!window.confirm('Tüm batch geçmişi silinsin mi? Bu işlem geri alınamaz.')) return
    setClearing(true)
    try {
      const res = await api.clearBatchHistory()
      toast.success(`${res.deleted} batch kaydı silindi`)
      queryClient.invalidateQueries({ queryKey: ['farming-analytics'] })
      onCleared?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Temizleme başarısız')
    } finally {
      setClearing(false)
    }
  }

  return (
    <GlassCard className="space-y-3">
      <PanelHeader
        icon={BarChart3}
        title="Batch Analitik"
        actions={
          <div className="flex items-center gap-2">
            {data && (
              <span className="text-[10px] text-slate-500 font-mono">
                {completed} / {total} üretildi (%{pct})
                {isFinished && <span className="ml-2 text-emerald-400">✓ Tamamlandı</span>}
              </span>
            )}
            <button
              onClick={clearHistory}
              disabled={clearing}
              aria-label="Batch geçmişini temizle"
              title="Batch geçmişini temizle"
              className="p-1 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-40 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        }
      />

      {!activeBatchId ? (
        <EmptyState icon={BarChart3} message="Farming başladığında analitikler burada görünecek" />
      ) : (
        <>
          {/* Özet Kartları */}
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 text-center">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 mx-auto mb-1" />
              <p className="text-lg font-bold text-emerald-400">{completed}</p>
              <p className="text-[10px] text-slate-500 uppercase">Başarılı</p>
            </div>
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-center">
              <XCircle className="w-4 h-4 text-red-400 mx-auto mb-1" />
              <p className="text-lg font-bold text-red-400">{failed}</p>
              <p className="text-[10px] text-slate-500 uppercase">Başarısız</p>
            </div>
            <div className="bg-iuGold/10 border border-iuGold/20 rounded-xl p-3 text-center">
              <Timer className="w-4 h-4 text-iuGold mx-auto mb-1" />
              <p className="text-lg font-bold text-iuGold">{total}</p>
              <p className="text-[10px] text-slate-500 uppercase">Toplam</p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <p className="text-[10px] text-slate-500 mb-2 uppercase tracking-wider">Üretim İlerleme Grafiği</p>
              <ResponsiveContainer width="100%" height={140}>
                <AreaChart data={throughput}>
                  <defs>
                    <linearGradient id="goldGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#D4AF37" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#D4AF37" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} width={35} />
                  <Tooltip
                    contentStyle={{ background: '#131F33', border: '1px solid #1E3252', borderRadius: 8, fontSize: 11 }}
                    labelStyle={{ color: '#D4AF37' }}
                  />
                  <Area type="monotone" dataKey="completed" name="Toplam Üretilen" stroke="#D4AF37" fill="url(#goldGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            <div>
              <p className="text-[10px] text-slate-500 mb-2 uppercase tracking-wider">Hata Dağılımı</p>
              {errorData.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={140}>
                    <PieChart>
                      <Pie data={errorData} cx="50%" cy="50%" innerRadius={30} outerRadius={55} dataKey="value" paddingAngle={3}>
                        {errorData.map((entry, i) => (
                          <Cell key={i} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{ background: '#131F33', border: '1px solid #1E3252', borderRadius: 8, fontSize: 11 }} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex flex-wrap gap-2 justify-center">
                    {errorData.map(d => (
                      <span key={d.name} className="flex items-center gap-1 text-[10px] text-slate-500">
                        <span className="w-2 h-2 rounded-full" style={{ background: d.color }} />
                        {d.name} ({d.value})
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <div className="flex items-center justify-center h-[140px]">
                  <p className="text-xs text-emerald-400/60">Hata yok</p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </GlassCard>
  )
}
