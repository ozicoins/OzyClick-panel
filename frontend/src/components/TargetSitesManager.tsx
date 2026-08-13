import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Globe2, Plus, X, Lock } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

export default function TargetSitesManager() {
  const queryClient = useQueryClient()
  const [newSite, setNewSite] = useState('')

  const { data } = useQuery({
    queryKey: ['target-sites'],
    queryFn: () => api.getTargetSites(),
  })
  const sites = data?.sites ?? []
  const defaults = data?.defaults ?? []

  const save = useMutation({
    mutationFn: (next: string[]) => api.setTargetSites(next),
    // PUT yalnızca {sites} döndürür; defaults'ı KORU (aksi halde "Temel havuz" kaybolurdu).
    onSuccess: (res) =>
      queryClient.setQueryData(
        ['target-sites'],
        (old: { sites: string[]; defaults: string[] } | undefined) => ({
          defaults: old?.defaults ?? [],
          sites: res.sites,
        }),
      ),
    onError: (e: Error) => toast.error(e.message),
  })

  const add = () => {
    let v = newSite.trim()
    if (!v) return
    if (!/^https?:\/\//i.test(v)) v = 'https://' + v
    if (sites.includes(v) || defaults.includes(v)) { setNewSite(''); return }
    save.mutate([...sites, v])
    setNewSite('')
  }
  const remove = (i: number) => save.mutate(sites.filter((_, idx) => idx !== i))

  return (
    <GlassCard className="space-y-3">
      <PanelHeader icon={Globe2} title="Hedef Siteler" />
      <p className="text-[11px] text-slate-500">
        Giriş sonrası her profil, havuzdan <span className="text-iuGold">rastgele</span> birkaç site gezip
        <span className="text-iuGold"> gerçek çerezleri</span> toplar (her cookie farklı parmak izi).
      </p>

      {/* Google — sabit varsayılan hedef */}
      <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-iuGold/5 border border-iuGold/20 text-[11px]">
        <Lock className="w-3 h-3 text-iuGold flex-shrink-0" />
        <span className="text-iuGold font-medium">Google</span>
        <span className="text-slate-500">— giriş + ısıtma (varsayılan, her zaman)</span>
      </div>

      {/* Temel siteler — sabit havuz (silinemez), her profilde rastgele seçilir */}
      {defaults.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-slate-500 flex items-center gap-1">
            <Lock className="w-2.5 h-2.5 text-slate-500" /> Temel havuz (her profilde rastgele 2–5 tanesi)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {defaults.map((d) => (
              <span key={d} className="px-2 py-0.5 rounded-full text-[11px] bg-iuGold/5 text-slate-400 border border-iuGold/15">
                {d.replace(/^https?:\/\//, '').replace(/^www\./, '')}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Kullanıcının eklediği ekstra hedefler */}
      {sites.length > 0 && (
        <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto pr-1" role="list" aria-label="Eklediğin hedef siteler">
          {sites.map((s, i) => (
            <span key={`${s}-${i}`} role="listitem"
              className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs bg-iuNavy/50 text-slate-300 border border-iuBorder max-w-full">
              <span className="truncate">{s.replace(/^https?:\/\//, '')}</span>
              <button onClick={() => remove(i)} disabled={save.isPending} className="hover:text-red-400 flex-shrink-0" aria-label={`${s} kaldır`}>
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={newSite}
          onChange={e => setNewSite(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="trendyol.com, hepsiburada.com ..."
          aria-label="Hedef site ekle"
          className="flex-1 bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none"
        />
        <button onClick={add} disabled={!newSite.trim() || save.isPending} aria-label="Site ekle"
          className="px-3 py-1.5 rounded-lg bg-iuGold/10 text-iuGold hover:bg-iuGold/20 disabled:opacity-30 transition-colors">
          <Plus className="w-4 h-4" />
        </button>
      </div>
      <p className="text-[10px] text-slate-600">Not: hedef site çerezleri yalnızca GERÇEK modda toplanır (DRY-RUN'da sentetiktir).</p>
    </GlassCard>
  )
}
