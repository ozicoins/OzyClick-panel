import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { JsonView, darkStyles } from 'react-json-view-lite'
import 'react-json-view-lite/dist/index.css'
import { Cookie, Search, Eye, EyeOff, Smartphone, Download, Activity, CheckCircle2, XCircle } from 'lucide-react'
import toast from 'react-hot-toast'

type ExportFmt = 'adswhite' | 'gologin' | 'universal' | 'netscape' | 'raw'
const FORMAT_OPTS: { v: ExportFmt; label: string }[] = [
  { v: 'adswhite', label: 'adswhite (fingerprint gömülü)' },
  { v: 'gologin', label: 'GoLogin' },
  { v: 'universal', label: 'Universal (AdsPower/Dolphin/Octo/Multilogin)' },
  { v: 'netscape', label: 'Netscape (cookies.txt)' },
  { v: 'raw', label: 'Playwright (ham)' },
]
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'
import EmptyState from './ui/EmptyState'
import Skeleton from './ui/Skeleton'

interface Props {
  email: string
}

export default function CookieInspector({ email }: Props) {
  const [profileIndex, setProfileIndex] = useState(1)
  const [showValues, setShowValues] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [fmt, setFmt] = useState<ExportFmt>('adswhite')

  const liveMut = useMutation({
    mutationFn: () => api.checkLive(email, profileIndex),
    onError: (e: Error) => toast.error(e.message),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['cookie-inspector', email, profileIndex],
    queryFn: () => api.inspectCookie(email, profileIndex),
    enabled: !!email,
  })

  const cookies = data?.cookies ?? []
  const filtered = cookies
    .filter((c) =>
      !searchTerm ||
      c.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.domain.toLowerCase().includes(searchTerm.toLowerCase())
    )
    .map(c => showValues ? c : { ...c, value: c.value.slice(0, 8) + '...' })

  return (
    <GlassCard className="space-y-3">
      <PanelHeader
        icon={Cookie}
        title="Cookie Inspector"
        actions={
          <button
            onClick={() => setShowValues(!showValues)}
            className="p-1.5 rounded-lg bg-iuNavy/50 border border-iuBorder text-slate-400 hover:text-iuGold transition-colors"
            aria-label={showValues ? 'Değerleri gizle' : 'Değerleri göster'}
          >
            {showValues ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        }
      />

      {!email ? (
        <EmptyState icon={Cookie} message="Hesap seçin" />
      ) : (
        <>
          <div className="flex gap-2">
            <div className="flex items-center gap-2 flex-1 bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-1.5">
              <Search className="w-3 h-3 text-slate-500 flex-shrink-0" aria-hidden="true" />
              <input
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                placeholder="Cookie ara..."
                aria-label="Cookie ara"
                className="bg-transparent text-xs text-slate-300 w-full focus:outline-none"
              />
            </div>
            <label className="sr-only" htmlFor="profile-index">Profil numarası</label>
            <input
              id="profile-index"
              type="number"
              min={1}
              value={profileIndex}
              onChange={e => setProfileIndex(Math.max(1, Math.floor(Number(e.target.value)) || 1))}
              className="w-16 bg-iuNavy/50 border border-iuBorder rounded-lg px-2 py-1.5 text-xs text-slate-300 text-center focus:border-iuGold focus:outline-none"
            />
          </div>

          {data?.device && (
            <div className="flex items-center gap-1.5 text-[10px] text-iuGold/90 bg-iuGold/5 border border-iuGold/15 rounded-lg px-2.5 py-1.5">
              <Smartphone className="w-3 h-3 flex-shrink-0" aria-hidden="true" />
              <span className="font-medium">{data.device}</span>
              {data.user_agent && (
                <span className="text-slate-500 truncate hidden sm:inline">· {data.user_agent}</span>
              )}
            </div>
          )}

          {/* CANLI KONTROL + ÇOK-FORMAT EXPORT + fingerprint eşleştirme */}
          {cookies.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => liveMut.mutate()}
                  disabled={liveMut.isPending}
                  className="px-3 py-1.5 rounded-lg bg-iuNavy/50 text-slate-300 border border-iuBorder hover:text-iuGold disabled:opacity-40 text-[11px] flex items-center gap-1.5 transition-colors">
                  <Activity className={`w-3.5 h-3.5 ${liveMut.isPending ? 'animate-pulse' : ''}`} />
                  {liveMut.isPending ? 'Kontrol ediliyor...' : 'Canlı mı?'}
                </button>
                {liveMut.data && (
                  liveMut.data.skipped
                    ? <span className="text-[11px] text-amber-400 flex items-center gap-1"><Activity className="w-3.5 h-3.5" /> ATLANDI · {liveMut.data.detail}</span>
                    : liveMut.data.alive
                    ? <span className="text-[11px] text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> AKTİF ✓</span>
                    : <span className="text-[11px] text-red-400 flex items-center gap-1"><XCircle className="w-3.5 h-3.5" /> PASİF · {liveMut.data.detail}</span>
                )}
              </div>
              <div className="flex gap-2">
                <select
                  value={fmt}
                  onChange={e => setFmt(e.target.value as ExportFmt)}
                  className="flex-1 min-w-0 bg-iuNavy/50 border border-iuBorder rounded-lg px-2 py-1.5 text-[11px] text-slate-300 focus:border-iuGold focus:outline-none">
                  {FORMAT_OPTS.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
                </select>
                <button
                  onClick={() => { api.downloadSingle(email, profileIndex, fmt).catch((e: Error) => toast.error(e.message)) }}
                  className="px-3 py-1.5 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/20 hover:bg-iuGold/20 text-[11px] flex items-center gap-1.5 flex-shrink-0 transition-colors">
                  <Download className="w-3.5 h-3.5" /> İndir
                </button>
                {data?.user_agent && (
                  <button
                    onClick={() => { navigator.clipboard?.writeText(data.user_agent || ''); toast.success('User-Agent kopyalandı') }}
                    className="px-2.5 py-1.5 rounded-lg bg-iuNavy/50 text-slate-400 border border-iuBorder hover:text-iuGold text-[11px] flex-shrink-0">
                    UA
                  </button>
                )}
              </div>
              <p className="text-[10px] text-slate-600 leading-relaxed">
                <b className="text-slate-400">adswhite / universal</b> → fingerprint gömülü. Kullandığın araçta
                <b className="text-slate-400"> UA</b> ({data?.device}) + <b className="text-slate-400">Türk proxy</b> eşleştir → pasiflik olmaz.
              </p>
            </div>
          )}

          <div className="bg-black/30 rounded-xl p-3 max-h-56 overflow-y-auto text-xs">
            {isLoading ? (
              <Skeleton rows={4} />
            ) : filtered.length === 0 ? (
              <p className="text-slate-600 text-center py-4">Cookie bulunamadı</p>
            ) : (
              <JsonView
                data={{ cookies: filtered }}
                style={{
                  ...darkStyles,
                  container: 'bg-transparent',
                  basicChildStyle: 'pl-4',
                  label: 'text-iuGold mr-2',
                  stringValue: 'text-emerald-400',
                  numberValue: 'text-cyan-400',
                  booleanValue: 'text-amber-400',
                  nullValue: 'text-slate-500',
                }}
              />
            )}
          </div>
        </>
      )}
    </GlassCard>
  )
}
