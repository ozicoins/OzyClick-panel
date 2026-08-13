import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, ToggleLeft, ToggleRight, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

export default function RunModeSettings() {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['run-mode'],
    queryFn: () => api.getRunMode(),
  })

  const mutation = useMutation({
    mutationFn: (dry: boolean) => api.setRunMode(dry),
    onSuccess: (res) => {
      queryClient.setQueryData(['run-mode'], res)
      toast.success(res.dry_run ? 'DRY-RUN açıldı (sentetik)' : 'GERÇEK mod açıldı')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const dryRun = data?.dry_run ?? true

  return (
    <GlassCard className="space-y-3">
      <PanelHeader icon={FlaskConical} title="Çalışma Modu" />

      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-slate-400">DRY-RUN (test modu)</p>
          <p className="text-[10px] text-slate-600">
            Açık: sentetik çerez, tarayıcı/proxy YOK · Kapalı: gerçek üretim
          </p>
        </div>
        <button
          onClick={() => mutation.mutate(!dryRun)}
          disabled={mutation.isPending}
          aria-pressed={dryRun}
          aria-label={dryRun ? 'DRY-RUN kapat' : 'DRY-RUN aç'}
          className={`transition-colors ${dryRun ? 'text-emerald-400' : 'text-slate-600'} disabled:opacity-50`}
        >
          {dryRun ? <ToggleRight className="w-8 h-8" /> : <ToggleLeft className="w-8 h-8" />}
        </button>
      </div>

      <div className={`flex items-center gap-2 rounded-lg p-2 text-[11px] ${
        dryRun ? 'bg-emerald-500/5 text-emerald-400' : 'bg-amber-500/10 text-amber-400'
      }`}>
        {dryRun ? (
          <span>Şu an TEST modunda — hiçbir gerçek tarayıcı açılmaz, proxy/kredi harcanmaz.</span>
        ) : (
          <>
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
            <span>GERÇEK mod açık — Chromium açılır, ScrapingBee kredisi harcanır. Önce küçük count ile deneyin.</span>
          </>
        )}
      </div>
    </GlassCard>
  )
}
