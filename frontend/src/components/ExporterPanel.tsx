import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileJson, Archive, Trash2, RefreshCw, Package } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

interface Props {
  email: string
}

type AllFmt = 'adswhite' | 'gologin' | 'universal' | 'netscape' | 'raw'

export default function ExporterPanel({ email }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [allFmt, setAllFmt] = useState<AllFmt>('adswhite')
  const queryClient = useQueryClient()

  const { data: stats, refetch, isFetching } = useQuery({
    queryKey: ['export-stats'],
    // Canlı artış WS'ten (her ✓ başarıda invalidate — useFarmingLogs); bu interval yalnız
    // WS kopukken güvenlik ağı (15sn→5sn: daha responsive).
    queryFn: () => api.getExportStats(),
    refetchInterval: 5_000,
  })
  const total = stats?.total_profiles ?? 0

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
