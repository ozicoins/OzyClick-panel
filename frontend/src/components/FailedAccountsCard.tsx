import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, X, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

// Ham sebebi kısa okunabilir etikete çevir.
const shortReason = (r: string): string => {
  if (/REDDET/i.test(r)) return 'Google reddetti (hesap/IP işaretli, çok deneme)'
  if (/2FA|EK DOĞRULAMA|challenge/i.test(r)) return '2FA ek doğrulama istiyor (kurtarma/onay)'
  if (/parola/i.test(r)) return 'Parola adımı gelmedi'
  return r.length > 70 ? r.slice(0, 70) + '…' : r
}

// Çıktılar sekmesi: login veremeyen SORUNLU hesaplar (2FA ek-doğrulama / REDDETTİ). Üretimde kalıcı
// kaydedilir → panel yenilense de kalır. Sorun yoksa kart görünmez.
export default function FailedAccountsCard() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['failed-accounts'],
    queryFn: () => api.getFailedAccounts(),
    refetchInterval: 15_000,
  })
  const remove = useMutation({
    mutationFn: (email: string) => api.removeFailedAccount(email),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['failed-accounts'] }),
    onError: () => toast.error('Çıkarılamadı'),
  })
  const clearAll = useMutation({
    mutationFn: () => api.clearFailedAccounts(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['failed-accounts'] }); toast.success('Liste temizlendi') },
    onError: () => toast.error('Temizlenemedi'),
  })

  const accounts = data?.accounts ?? []
  if (accounts.length === 0) return null   // sorun yoksa kartı hiç gösterme

  return (
    <GlassCard className="space-y-2">
      <PanelHeader
        icon={AlertTriangle}
        title={`Sorunlu Hesaplar (${accounts.length})`}
        actions={
          <button onClick={() => clearAll.mutate()} disabled={clearAll.isPending}
            className="p-1 rounded text-slate-500 hover:text-red-400 transition-colors" title="Tümünü temizle">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        }
      />
      <p className="text-[10px] text-slate-600 leading-snug">
        Bu hesaplar login veremedi (Google ek-doğrulama/onay istiyor ya da işaretli) → otomatik üretilemezler.
        Secret/kurtarma/durumu düzelt, sonra <b className="text-slate-400">×</b> ile listeden çıkar. (Üretimde otomatik birikir, yenilemede kalır.)
      </p>
      <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
        {accounts.map(a => (
          <div key={a.email} className="flex items-center gap-2 text-[11px] border-b border-iuBorder/20 py-1.5">
            <div className="min-w-0 flex-1">
              <p className="text-slate-300 truncate font-mono">{a.email}</p>
              <p className="text-amber-400/90 text-[10px] truncate">
                {shortReason(a.reason)}{a.at && <span className="text-slate-600"> · {a.at}</span>}
              </p>
            </div>
            <button onClick={() => remove.mutate(a.email)} disabled={remove.isPending}
              className="p-1 rounded text-slate-600 hover:text-red-400 flex-shrink-0" title="Listeden çıkar (düzelttim)">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </GlassCard>
  )
}
