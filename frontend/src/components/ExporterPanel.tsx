import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileJson, Archive, Trash2, RefreshCw, Package, Cloud, CloudUpload } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

interface Props {
  email: string
}

type AllFmt = 'adswhite' | 'gologin' | 'universal' | 'netscape' | 'raw'

// Bayt → okunaklı (0 B / 940 KB / 7.4 MB)
const humanSize = (n: number): string => {
  if (!n || n < 0) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0, v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(i === 0 || v >= 100 ? 0 : 1)} ${u[i]}`
}

// ozy_cookies_20260813_190148.tar.gz.enc → "13.08.2026 19:01"
const backupDate = (name: string, modTime?: string): string => {
  const m = name.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/)
  if (m) return `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}`
  if (modTime) return new Date(modTime).toLocaleString('tr-TR')
  return name
}

export default function ExporterPanel({ email }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [allFmt, setAllFmt] = useState<AllFmt>('adswhite')
  const queryClient = useQueryClient()

  const { data: stats, refetch, isFetching } = useQuery({
    queryKey: ['export-stats'],
    // Canlı artış: her ✓ başarıda WS invalidate (useFarmingLogs) + bu interval güvenlik ağı.
    // refetchIntervalInBackground: panel arka-plan sekmedeyken bile artmaya devam etsin (üretimi
    // izlerken başka sekmeye geçince donmasın). 5→3sn: daha canlı.
    queryFn: () => api.getExportStats(),
    refetchInterval: 3_000,
    refetchIntervalInBackground: true,
  })
  const total = stats?.total_profiles ?? 0

  // MANUEL yedek: tetiklenince yeni yedek Drive'da görünene kadar sık (3sn) yoklar.
  const [backingUp, setBackingUp] = useState(false)
  const beforeRef = useRef<string | undefined>(undefined)   // tetikten önceki en son yedek adı
  const startedRef = useRef(0)

  // Google Drive şifreli yedek durumu (host cron ~30 dk; manuel yedekte 3sn'ye hızlanır).
  const { data: backups } = useQuery({
    queryKey: ['drive-backups'],
    queryFn: () => api.getBackups(),
    refetchInterval: backingUp ? 3_000 : 60_000,
  })

  // Tetiklenen manuel yedek tamamlandı mı? (yeni dosya adı belirdiyse VEYA 2 dk zaman aşımı)
  useEffect(() => {
    if (!backingUp) return
    const latest = backups?.backups?.[0]?.name
    if (latest && latest !== beforeRef.current) {
      setBackingUp(false)
      toast.success('Yeni yedek alındı ✓')
    } else if (Date.now() - startedRef.current > 120_000) {
      setBackingUp(false)
      toast('Yedek arka planda sürüyor — birazdan listede görünecek', { icon: '⏳' })
    }
  }, [backups, backingUp])

  const doBackupNow = async () => {
    if (backingUp) return
    beforeRef.current = backups?.backups?.[0]?.name
    startedRef.current = Date.now()
    setBackingUp(true)
    try {
      const res = await api.backupNow()
      toast.success(res.detail || 'Yedekleme başlatıldı…')
    } catch (e) {
      setBackingUp(false)
      toast.error(e instanceof Error ? e.message : 'Yedekleme başlatılamadı')
    }
  }

  // TÜM HAVUZ toplu indir (seçilen format)
  const downloadAll = async (fmt: AllFmt) => {
    if (busy) return
    setBusy('all-' + fmt)
    try { await api.downloadAll(fmt) }
    catch (e) { toast.error(e instanceof Error ? e.message : 'İndirme başarısız') }
    finally { setBusy(null) }
  }

  const purgeAll = async () => {
    if (busy) return
    if (!window.confirm('Havuzdaki TÜM üretilmiş çıktılar silinsin mi? Bu işlem geri alınamaz.')) return
    setBusy('purge-all')
    try {
      const res = await api.purgeAllOutputs()
      toast.success(`${res.deleted_profiles} profil silindi (${res.deleted_accounts} hesap)`)
      refetch()
      queryClient.invalidateQueries({ queryKey: ['cookie-inspector'] })
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Temizleme başarısız') }
    finally { setBusy(null) }
  }

  // Seçili hesap indir/temizle
  const run = async (kind: 'zip' | 'manifest') => {
    if (!email || busy) return
    setBusy(kind)
    try {
      if (kind === 'zip') await api.downloadZip(email)
      else await api.downloadManifest(email)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'İndirme başarısız')
    } finally { setBusy(null) }
  }

  const purge = async () => {
    if (!email || busy) return
    if (!window.confirm(`"${email}" hesabının üretilmiş tüm profilleri silinsin mi? Geri alınamaz.`)) return
    setBusy('purge')
    try {
      const res = await api.purgeAccount(email)
      toast.success(`${res.deleted_files} dosya silindi`)
      refetch()
      queryClient.invalidateQueries({ queryKey: ['cookie-inspector', email] })
      queryClient.invalidateQueries({ queryKey: ['proxy-map', email] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Temizleme başarısız')
    } finally { setBusy(null) }
  }

  return (
    <GlassCard className="space-y-3">
      <PanelHeader
        icon={Download}
        title="Çıktılar & İndirme"
        actions={
          <button onClick={() => refetch()} aria-label="Sayımı yenile" title="Yenile"
            className="p-1 rounded-lg text-slate-500 hover:text-iuGold hover:bg-iuGold/10 transition-colors">
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
          </button>
        }
      />

      {/* TÜM HAVUZ — toplam sayım + toplu indir + toplu sil (her zaman görünür) */}
      <div className="bg-iuNavy/30 rounded-lg p-3 border border-iuBorder space-y-2">
        <div className="flex items-baseline justify-between">
          <span className="text-[11px] text-slate-500 uppercase tracking-wider">Tüm Havuz</span>
          <span className="text-lg font-bold text-iuGold leading-none">
            {total}<span className="text-[10px] text-slate-500 font-normal ml-1">çerez · {stats?.accounts ?? 0} hesap</span>
          </span>
        </div>
        <div className="flex gap-2">
          <select value={allFmt} onChange={e => setAllFmt(e.target.value as AllFmt)}
            className="flex-1 min-w-0 bg-iuNavy/50 border border-iuBorder rounded-lg px-2 py-2 text-xs text-slate-300 focus:border-iuGold focus:outline-none">
            <option value="adswhite">OzyClick (fingerprint gömülü)</option>
            <option value="gologin">GoLogin</option>
            <option value="universal">Universal (AdsPower/Dolphin/Octo/Multilogin)</option>
            <option value="netscape">Netscape (cookies.txt)</option>
            <option value="raw">Playwright (ham)</option>
          </select>
          <button onClick={() => downloadAll(allFmt)} disabled={busy !== null || total === 0}
            className="px-4 py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-40 text-xs flex items-center gap-1.5 flex-shrink-0 transition-colors">
            <Package className="w-3.5 h-3.5" /> {busy?.startsWith('all-') ? '...' : 'Tümünü İndir'}
          </button>
        </div>
        <button onClick={purgeAll} disabled={busy !== null || total === 0}
          className="w-full py-1.5 rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 disabled:opacity-40 text-[11px] flex items-center justify-center gap-1.5 transition-colors">
          <Trash2 className="w-3.5 h-3.5" /> {busy === 'purge-all' ? 'Siliniyor...' : 'Tümünü Sil'}
        </button>
        <p className="text-[10px] text-slate-600 leading-snug">
          İstediğin kadar kez indirebilirsin. <b className="text-slate-400">OzyClick ZIP</b>'i çıkar → OzyClick'te "Cookie Klasörü" olarak yükle.
        </p>
      </div>

      {/* GOOGLE DRIVE YEDEKLERİ — otomatik şifreli yedeklerin durumu (adet/boyut/son yedekler) */}
      <div className="bg-iuNavy/30 rounded-lg p-3 border border-iuBorder space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Cloud className="w-3.5 h-3.5 text-iuGold" aria-hidden="true" />
            <span className="text-[11px] text-slate-500 uppercase tracking-wider">Drive Yedekleri</span>
          </div>
          {backups?.enabled && (
            <span className="text-[10px] text-emerald-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 pulse-dot inline-block" /> otomatik · şifreli
            </span>
          )}
        </div>

        {/* MANUEL yedek — otomatik 6 saatliğe ek, anında Drive'a alır */}
        <button
          onClick={doBackupNow}
          disabled={backingUp}
          className="w-full py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-50 text-xs flex items-center justify-center gap-1.5 transition-colors">
          <CloudUpload className={`w-3.5 h-3.5 ${backingUp ? 'animate-pulse' : ''}`} aria-hidden="true" />
          {backingUp ? 'Yedekleniyor…' : 'Şimdi Yedekle'}
        </button>

        {!backups ? (
          <p className="text-[11px] text-slate-600">Yükleniyor…</p>
        ) : backups.count === 0 ? (
          <p className="text-[11px] text-slate-600">{backups.detail || 'Henüz yedek yok.'}</p>
        ) : (
          <>
            <div className="flex items-baseline justify-between">
              <span className="text-[10px] text-slate-500">
                {backups.cron}{backups.retention_days ? ` · ${backups.retention_days}g saklama` : ''}
              </span>
              <span className="text-base font-bold text-iuGold leading-none">
                {backups.count}
                <span className="text-[10px] text-slate-500 font-normal ml-1">yedek · {humanSize(backups.total_size)}</span>
              </span>
            </div>
            <div className="max-h-28 overflow-y-auto space-y-0.5 pr-1">
              {backups.backups.map(b => (
                <div key={b.name} className="flex items-center justify-between text-[10px] font-mono border-b border-iuBorder/20 py-0.5">
                  <span className="text-slate-300">{backupDate(b.name, b.modTime)}</span>
                  <span className="text-slate-500">{humanSize(b.size)}</span>
                </div>
              ))}
            </div>
            {backups.updated_at && (
              <p className="text-[10px] text-slate-600">
                Son kontrol: {new Date(backups.updated_at).toLocaleString('tr-TR')} · Google Drive
              </p>
            )}
          </>
        )}
      </div>

      {/* SEÇİLİ HESAP — tek hesap indir/temizle */}
      {email && (
        <div className="space-y-2">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider truncate">Seçili: {email}</p>
          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => run('zip')} disabled={busy !== null}
              className="py-2 rounded-lg bg-iuNavy/50 text-slate-300 border border-iuBorder hover:border-iuGold/30 disabled:opacity-40 text-xs flex items-center justify-center gap-1.5 transition-all">
              <Archive className="w-3.5 h-3.5" /> {busy === 'zip' ? '...' : 'Hesap ZIP'}
            </button>
            <button onClick={() => run('manifest')} disabled={busy !== null}
              className="py-2 rounded-lg bg-iuNavy/50 text-slate-400 border border-iuBorder hover:border-iuGold/30 disabled:opacity-40 text-xs flex items-center justify-center gap-1.5 transition-all">
              <FileJson className="w-3.5 h-3.5" /> {busy === 'manifest' ? '...' : 'Manifest'}
            </button>
          </div>
          <button onClick={purge} disabled={busy !== null}
            className="w-full py-1.5 rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 disabled:opacity-40 text-[11px] flex items-center justify-center gap-1.5 transition-all">
            <Trash2 className="w-3.5 h-3.5" /> {busy === 'purge' ? 'Temizleniyor...' : 'Bu Hesabı Temizle'}
          </button>
        </div>
      )}
    </GlassCard>
  )
}
