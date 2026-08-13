import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, HardDriveDownload, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import type { ScheduleConfig, BackupConfig } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

const INTERVALS = [1, 2, 3, 4, 6, 8, 12, 24]
const inputCls = 'bg-iuNavy/50 border border-iuBorder rounded-lg px-2 py-1.5 text-xs text-slate-200 focus:border-iuGold focus:outline-none'

export default function AutomationSettings() {
  const qc = useQueryClient()

  // --- Zamanlayıcı ---
  const { data: sched } = useQuery<ScheduleConfig>({ queryKey: ['schedule'], queryFn: () => api.getSchedule() })
  const [s, setS] = useState<Partial<ScheduleConfig>>({})
  useEffect(() => { if (sched) setS(sched) }, [sched])
  const saveSched = useMutation({
    mutationFn: () => api.setSchedule({
      enabled: s.enabled, time: s.time, mode: s.mode, count_per_account: s.count_per_account,
      lifespan_days: s.lifespan_days, sector: s.sector, daily_summary: s.daily_summary, summary_time: s.summary_time,
    }),
    onSuccess: (d) => { qc.setQueryData(['schedule'], d); toast.success('Zamanlayıcı kaydedildi') },
    onError: (e: any) => toast.error(e?.message || 'Kaydedilemedi'),
  })

  // --- Yedek ayarları ---
  const { data: bcfg } = useQuery<BackupConfig>({ queryKey: ['backup-config'], queryFn: () => api.getBackupConfig() })
  const [b, setB] = useState<BackupConfig>({ interval_hours: 6, retention_days: 14 })
  useEffect(() => { if (bcfg) setB(bcfg) }, [bcfg])
  const saveBackup = useMutation({
    mutationFn: () => api.setBackupConfig(b),
    onSuccess: (d) => { qc.setQueryData(['backup-config'], d); toast.success('Yedek ayarı kaydedildi (~5 dk içinde geçerli)') },
    onError: (e: any) => toast.error(e?.message || 'Kaydedilemedi'),
  })

  // --- Otomatik ölü-çerez temizliği ---
  const { data: cleanup } = useQuery({ queryKey: ['auto-cleanup'], queryFn: () => api.getAutoCleanup() })
  const setCleanup = useMutation({
    mutationFn: (v: boolean) => api.setAutoCleanup(v),
    onSuccess: (d) => { qc.setQueryData(['auto-cleanup'], d); toast.success(d.enabled ? 'Otomatik temizlik AÇIK' : 'Otomatik temizlik KAPALI') },
    onError: () => toast.error('Değiştirilemedi'),
  })

  return (
    <GlassCard className="space-y-4">
      <PanelHeader icon={CalendarClock} title="Otomasyon" />

      {/* Üretim Zamanlayıcı */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-300 flex items-center gap-1.5"><CalendarClock className="w-3.5 h-3.5 text-iuGold" /> Üretim Zamanlayıcı</span>
          <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
            <input type="checkbox" checked={!!s.enabled} onChange={e => setS(v => ({ ...v, enabled: e.target.checked }))} className="accent-iuGold" />
            Açık
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="text-[10px] text-slate-500 space-y-1">
            <span>Saat (Türkiye)</span>
            <input type="time" value={s.time || '03:00'} onChange={e => setS(v => ({ ...v, time: e.target.value }))} className={`${inputCls} w-full`} />
          </label>
          <label className="text-[10px] text-slate-500 space-y-1">
            <span>Mod</span>
            <select value={s.mode || 'FAST'} onChange={e => setS(v => ({ ...v, mode: e.target.value as ScheduleConfig['mode'] }))} className={`${inputCls} w-full`}>
              <option value="SAFE">Safe</option><option value="FAST">Fast</option><option value="TURBO">Turbo</option>
            </select>
          </label>
          <label className="text-[10px] text-slate-500 space-y-1">
            <span>Hesap başına adet</span>
            <input type="number" min={1} value={s.count_per_account ?? 20} onChange={e => setS(v => ({ ...v, count_per_account: Math.max(1, Number(e.target.value) || 1) }))} className={`${inputCls} w-full`} />
          </label>
          <label className="text-[10px] text-slate-500 space-y-1">
            <span>Ömür (gün)</span>
            <select value={s.lifespan_days ?? 5} onChange={e => setS(v => ({ ...v, lifespan_days: Number(e.target.value) }))} className={`${inputCls} w-full`}>
              <option value={3}>3</option><option value={4}>4</option><option value={5}>5</option>
            </select>
          </label>
        </div>
        <label className="flex items-center justify-between gap-2 text-[11px] text-slate-400">
          <span className="flex items-center gap-1.5"><input type="checkbox" checked={!!s.daily_summary} onChange={e => setS(v => ({ ...v, daily_summary: e.target.checked }))} className="accent-iuGold" /> Günlük özet (Telegram)</span>
          <input type="time" value={s.summary_time || '09:00'} onChange={e => setS(v => ({ ...v, summary_time: e.target.value }))} className={inputCls} />
        </label>
        <button onClick={() => saveSched.mutate()} disabled={saveSched.isPending}
          className="w-full py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-40 text-xs font-medium transition-colors">
          {saveSched.isPending ? 'Kaydediliyor...' : 'Zamanlayıcıyı Kaydet'}
        </button>
        <p className="text-[10px] text-slate-600 leading-snug">
          Açıkken her gün belirtilen saatte (<b className="text-slate-400">Türkiye saati</b>) havuzdaki TÜM hesaplar için üretim başlar (aktif üretim varsa atlanır).
        </p>
      </div>

      <div className="h-px bg-iuBorder/60" />

      {/* Yedek Ayarları */}
      <div className="space-y-2">
        <span className="text-xs text-slate-300 flex items-center gap-1.5"><HardDriveDownload className="w-3.5 h-3.5 text-iuGold" /> Yedek Sıklığı & Saklama</span>
        <div className="grid grid-cols-2 gap-2">
          <label className="text-[10px] text-slate-500 space-y-1">
            <span>Sıklık</span>
            <select value={b.interval_hours} onChange={e => setB(v => ({ ...v, interval_hours: Number(e.target.value) }))} className={`${inputCls} w-full`}>
              {INTERVALS.map(h => <option key={h} value={h}>{h === 24 ? 'Günde bir' : `${h} saatte bir`}</option>)}
            </select>
          </label>
          <label className="text-[10px] text-slate-500 space-y-1">
            <span>Saklama (gün)</span>
            <input type="number" min={1} max={365} value={b.retention_days} onChange={e => setB(v => ({ ...v, retention_days: Math.max(1, Math.min(365, Number(e.target.value) || 1)) }))} className={`${inputCls} w-full`} />
          </label>
        </div>
        <button onClick={() => saveBackup.mutate()} disabled={saveBackup.isPending}
          className="w-full py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-40 text-xs font-medium transition-colors">
          {saveBackup.isPending ? 'Kaydediliyor...' : 'Yedek Ayarını Kaydet'}
        </button>
      </div>

      <div className="h-px bg-iuBorder/60" />

      {/* Otomatik ölü-çerez temizliği */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-300 flex items-center gap-1.5"><Trash2 className="w-3.5 h-3.5 text-iuGold" /> Ölü çerezleri otomatik sil</span>
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
          <input type="checkbox" checked={!!cleanup?.enabled} onChange={e => setCleanup.mutate(e.target.checked)} className="accent-iuGold" />
          {cleanup?.enabled ? 'Açık' : 'Kapalı'}
        </label>
      </div>
      <p className="text-[10px] text-slate-600 leading-snug -mt-2">
        Açıkken "Tümünü Tara" ölü bulduğu çerezleri siler. Proxy'si çözülemeyip atlananlar SİLİNMEZ (güvenli).
      </p>
    </GlassCard>
  )
}
