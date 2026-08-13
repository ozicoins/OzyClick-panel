import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import type { LiveScanStatus } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

// Klasör adı → okunaklı email (backend sanitize'ının tersi; gmail için birebir doğru).
const folderToEmail = (f: string) => f.replace(/_at_/g, '@').replace(/_/g, '.')
const pct = (n: number, d: number) => (d > 0 ? (n / d) * 100 : 0)

// Havuz Sağlığı — TOPLU canlılık taraması + hesap kırılımı. "Tümünü Tara" tüm çerezleri kendi
// doğum-proxy'siyle Google'a uğratıp aktif mi kontrol eder (Inspector'ın toplu, tek-tık hâli).
export default function PoolHealthCard() {
  const qc = useQueryClient()
  const kickRef = useRef(false)   // tıklamadan hemen sonra 'running' yakalanana kadar hızlı poll
  const [del, setDel] = useState<boolean | null>(null)   // bu taramada ölüleri sil? (null → global ayar)

  const { data: stats } = useQuery({
    queryKey: ['export-stats'],
    queryFn: () => api.getExportStats(),
    refetchInterval: 10_000,
  })
  // Global otomatik-temizlik ayarı → "ölüleri sil" onay kutusunun varsayılanı
  const { data: cleanup } = useQuery({ queryKey: ['auto-cleanup'], queryFn: () => api.getAutoCleanup() })
  const delDead = del === null ? !!cleanup?.enabled : del
  const { data: scan } = useQuery({
    queryKey: ['live-scan'],
    queryFn: () => api.getLiveScan(),
    // Tararken 2.5sn, boştayken 20sn (dışarıdan başlatılan taramayı da yakalar).
    refetchInterval: (query) => ((query.state.data?.running || kickRef.current) ? 2_500 : 20_000),
  })

  useEffect(() => { if (scan?.running) kickRef.current = false }, [scan?.running])

  const startMut = useMutation({
    mutationFn: () => api.startLiveScan(delDead),
    onSuccess: (r) => {
      kickRef.current = true
      qc.invalidateQueries({ queryKey: ['live-scan'] })
      toast.success(r.detail)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const running = !!scan?.running
  const total = scan?.total || stats?.total_profiles || 0
  const alive = scan?.alive ?? 0
  const dead = scan?.dead ?? 0
  const skipped = scan?.skipped ?? 0
  const checked = scan?.checked ?? 0
  const checkable = alive + dead
  const alivePct = Math.round(pct(alive, checkable))
  const accounts = Object.entries((scan?.per_account ?? {}) as Record<string, LiveScanStatus['per_account'][string]>)
  const neverScanned = !scan || (scan.total === 0 && !running && !scan.done)

  return (
    <GlassCard className="space-y-3">
      <PanelHeader
        icon={Activity}
        title="Havuz Sağlığı"
        actions={
          <button
            onClick={() => startMut.mutate()}
            disabled={running || startMut.isPending}
            className="px-3 py-1.5 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-50 text-[11px] flex items-center gap-1.5 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${running ? 'animate-spin' : ''}`} aria-hidden="true" />
            {running ? `Taranıyor ${checked}/${total}` : 'Tümünü Tara'}
          </button>
        }
      />

      <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer -mt-1">
        <input type="checkbox" checked={delDead} onChange={e => setDel(e.target.checked)} className="accent-red-400" />
        Bu taramada <b className="text-red-400/90">ölüleri sil</b> {del === null && cleanup?.enabled ? '(Ayarlar: açık)' : ''}
      </label>

      <div className="bg-iuNavy/30 rounded-lg p-3 border border-iuBorder">
        <div className="flex items-baseline justify-between">
          <span className="text-[11px] text-slate-500 uppercase tracking-wider">Canlı Çerez</span>
          {scan?.updated_at && !running && (
            <span className="text-[10px] text-slate-600">son tarama: {new Date(scan.updated_at).toLocaleString('tr-TR')}</span>
          )}
        </div>

        {neverScanned ? (
          <p className="text-sm text-slate-500 mt-1">Henüz tarama yok — <b className="text-iuGold">Tümünü Tara</b> ile başlat.</p>
        ) : (
          <>
            <div className="flex items-end gap-2 mt-1">
              <span className="text-2xl font-bold text-emerald-400 leading-none">{alive}</span>
              <span className="text-sm text-slate-500 leading-none mb-0.5">/ {total} çerez</span>
              <span className="text-sm text-iuGold leading-none mb-0.5 ml-auto">%{alivePct} canlı</span>
            </div>
            <div className="mt-2 h-2 rounded-full bg-black/40 overflow-hidden flex">
              <div className="bg-emerald-500 h-full" style={{ width: `${pct(alive, total)}%` }} />
              <div className="bg-red-500 h-full" style={{ width: `${pct(dead, total)}%` }} />
              <div className="bg-amber-500/60 h-full" style={{ width: `${pct(skipped, total)}%` }} />
            </div>
            <div className="flex items-center gap-3 mt-1.5 text-[10px]">
              <span className="text-emerald-400">● {alive} canlı</span>
              <span className="text-red-400">● {dead} ölü</span>
              {skipped > 0 && <span className="text-amber-400">● {skipped} atlandı</span>}
              {running && <span className="text-slate-500 ml-auto">{checked}/{total} kontrol edildi…</span>}
            </div>
          </>
        )}
      </div>

      {accounts.length > 0 && (
        <div className="max-h-48 overflow-y-auto space-y-1 pr-1">
          {accounts.map(([folder, a]) => (
            <div key={folder} className="flex items-center gap-2 text-[11px] border-b border-iuBorder/20 py-1">
              <span className="truncate flex-1 text-slate-300">{folderToEmail(folder)}</span>
              <span className="text-emerald-400 flex-shrink-0">{a.alive}✓</span>
              {a.dead > 0 && <span className="text-red-400 flex-shrink-0">{a.dead}✗</span>}
              {a.skipped > 0 && <span className="text-amber-400 flex-shrink-0">{a.skipped}?</span>}
            </div>
          ))}
        </div>
      )}

      <p className="text-[10px] text-slate-600 leading-snug">
        Her çerez kendi <b className="text-slate-400">doğum-proxy'si + parmak izi</b>yle Google'a uğratılır (gerçek kontrol).
        Ağırdır — büyük havuzda birkaç dakika sürer. <span className="text-amber-400/80">?</span> = proxy çözülemedi, atlandı (çerez yakılmadı).
      </p>
    </GlassCard>
  )
}
