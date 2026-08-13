import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { HeartPulse, ToggleLeft, ToggleRight, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import type { KeepAliveStatus } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

export default function SessionKeepAlive() {
  const queryClient = useQueryClient()

  const { data } = useQuery<KeepAliveStatus>({
    queryKey: ['keep-alive-status'],
    queryFn: () => api.getKeepAliveStatus(),
    // Tur ÇALIŞIRKEN sık (2sn) → canlı ilerleme; boştayken seyrek (15sn).
    refetchInterval: (q) => ((q.state.data as KeepAliveStatus | undefined)?.running ? 2_000 : 15_000),
  })

  const toggleMutation = useMutation({
    mutationFn: () => api.toggleKeepAlive(),
    onSuccess: (result) => {
      queryClient.setQueryData(['keep-alive-status'], result)
    },
  })

  const pingNowMutation = useMutation({
    mutationFn: () => api.pingKeepAliveNow(),
    onSuccess: (r) => {
      toast.success(r.detail)
      // Tur bittikçe status güncellensin diye birkaç kez tazele
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['keep-alive-status'] }), 5_000)
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['keep-alive-status'] }), 20_000)
    },
    onError: () => toast.error('Tazeleme başlatılamadı'),
  })

  // Son ping'in üzerinden ne kadar geçti (tazelik göstergesi — "anlık gerçek çalışıyor mu")
  const pingAge = (iso: string | null): string => {
    if (!iso) return 'hiç'
    try {
      const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
      if (mins < 1) return 'az önce'
      if (mins < 60) return `${mins} dk önce`
      const hrs = Math.floor(mins / 60)
      if (hrs < 24) return `${hrs} saat önce`
      return `${Math.floor(hrs / 24)} gün önce`
    } catch { return '' }
  }

  const active = data?.active ?? false
  const lastPing = data?.last_ping ?? null
  const nextPing = data?.next_ping ?? null
  const successCount = data?.success_count ?? 0
  const totalCount = data?.total_count ?? 0
  const successRate = totalCount > 0 ? ((successCount / totalCount) * 100).toFixed(1) : '0'

  const formatPing = (iso: string | null) => {
    if (!iso) return '-'
    try {
      return new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
    } catch {
      return iso
    }
  }

  return (
    <GlassCard className="space-y-3">
      <PanelHeader icon={HeartPulse} title="Session Keep-Alive" />

      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-slate-400">Keep-alive modu</p>
          <p className="text-[10px] text-slate-600">24 saatte bir gerçek yenileme</p>
        </div>
        <button
          onClick={() => toggleMutation.mutate()}
          disabled={toggleMutation.isPending}
          aria-label={active ? 'Keep-alive kapat' : 'Keep-alive aç'}
          aria-pressed={active}
          className={`transition-colors ${active ? 'text-emerald-400' : 'text-slate-600'} disabled:opacity-50`}
        >
          {active ? <ToggleRight className="w-8 h-8" /> : <ToggleLeft className="w-8 h-8" />}
        </button>
      </div>

      {/* CANLI: tur çalışırken gerçek-zamanlı ilerleme (2sn'de bir güncellenir) */}
      {data?.running && (
        <div className="rounded-lg p-2.5 bg-iuGold/5 border border-iuGold/25 animate-fade-in">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-iuGold font-semibold flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full pulse-dot inline-block" /> Kontrol çalışıyor · CANLI
            </span>
            <span className="text-slate-400 mono-font tabular-nums">
              {data.processed ?? 0}/{totalCount} · {successCount} canlı
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-white/8 overflow-hidden mt-1.5">
            <div className="h-full rounded-full bg-iuGold transition-all duration-500"
              style={{ width: `${totalCount ? Math.round(((data.processed ?? 0) / totalCount) * 100) : 0}%` }} />
          </div>
        </div>
      )}

      <div className="rounded-lg p-2 text-[11px] leading-relaxed bg-iuNavy/30 text-slate-500">
        <b className="text-slate-400">GERÇEK modda:</b> her profilin çerezleri <b>kendi telefon parmak izi +
        proxy'siyle</b> yüklenip Google'a uğratılır → oturum sunucu tarafında tazelenir (<b>ömür uzar</b>)
        ve gerçek canlılık ölçülür. Ekran açılmaz, düşük eşzamanlılık. <b className="text-slate-400">DRY modda:</b> yalnızca
        sentetik profiller sayılır (canlılık doğrulanmaz).
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="bg-iuNavy/30 rounded-lg p-3 text-center">
          <p className="text-[10px] text-slate-500 mb-1">Son Yenileme</p>
          <p className="text-xs text-slate-400">{formatPing(lastPing)}</p>
          <p className="text-[10px] text-slate-600">{pingAge(lastPing)}</p>
        </div>
        <div className="bg-iuNavy/30 rounded-lg p-3 text-center">
          <p className="text-[10px] text-slate-500 mb-1">Sıradaki</p>
          <p className="text-xs text-slate-400">{formatPing(nextPing)}</p>
        </div>
      </div>

      {/* Elle tazeleme: 24 saati beklemeden hemen bir tur çalıştır → durum gerçek zamanlı görünür */}
      <button
        onClick={() => pingNowMutation.mutate()}
        disabled={!active || pingNowMutation.isPending}
        className="w-full py-2 rounded-xl bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-xs font-medium"
      >
        <RefreshCw className={`w-3.5 h-3.5 ${pingNowMutation.isPending ? 'animate-spin' : ''}`} />
        {pingNowMutation.isPending ? 'Tur başlatıldı...' : 'Şimdi Tazele (canlılığı gerçek-zaman kontrol et)'}
      </button>

      {active && totalCount > 0 && (
        successCount > 0 ? (
          <div className="bg-emerald-500/5 rounded-lg p-2 text-center">
            <p className="text-xs text-emerald-400">
              Canlı: %{successRate} ({successCount.toLocaleString('tr-TR')}/{totalCount.toLocaleString('tr-TR')})
            </p>
          </div>
        ) : (
          <div className="bg-red-500/5 rounded-lg p-2 text-center border border-red-500/20">
            <p className="text-[11px] text-red-400 leading-relaxed">
              ⚠️ {totalCount} profilden <b>hiçbiri canlı doğrulanamadı</b> (%0). Çerezler ölmüş
              <b> veya proxy Google'a ulaşamıyor</b> olabilir — proxy'yi test edin, taze çerez üretin.
            </p>
          </div>
        )
      )}
    </GlassCard>
  )
}
