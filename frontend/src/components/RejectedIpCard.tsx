import { useQuery } from '@tanstack/react-query'
import { ShieldAlert } from 'lucide-react'
import { api } from '../api/client'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

// "Google REDDETTİ" (hesap/IP işaretli, çok deneme) alan hesaplar. Bunlar HESABIN değil
// PROXY/IP'nin sorunu → strike YOK, otomatik başka proxy'yle tekrar denenir. Aynı proxy tekrar
// tekrar REDDETTİ verirse o proxy geçici flag'lenir (rotasyon dışı). Salt-görünürlük kartı.
export default function RejectedIpCard() {
  const { data } = useQuery({
    queryKey: ['rejected-ip'],
    queryFn: () => api.getRejectedIp(),
    refetchInterval: 15_000,
  })
  const accounts = data?.accounts ?? []
  if (accounts.length === 0) return null   // reddi yoksa kartı gösterme

  return (
    <GlassCard className="space-y-2">
      <PanelHeader icon={ShieldAlert} title={`IP Reddi · Proxy (${accounts.length})`} />
      <p className="text-[10px] text-slate-600 leading-snug">
        Bu hesaplar <b className="text-sky-400">Google REDDETTİ</b> aldı = IP/proxy işaretli (hesabın suçu değil).
        Strike verilmez, otomatik <b className="text-slate-400">başka proxy</b> ile tekrar denenir. Aynı proxy tekrarlarsa
        o proxy geçici olarak rotasyondan çıkarılır (flag).
      </p>
      <div className="max-h-40 overflow-y-auto space-y-1 pr-1">
        {accounts.map(a => (
          <div key={a.email} className="flex items-center gap-2 text-[11px] border-b border-iuBorder/20 py-1.5">
            <div className="min-w-0 flex-1">
              <p className="text-slate-300 truncate font-mono">{a.email}</p>
              <p className="text-sky-400/80 text-[10px] truncate">
                IP/proxy reddi{a.proxy && <span className="text-slate-600"> · {a.proxy.replace(/^https?:\/\//, '')}</span>}
                {a.at && <span className="text-slate-600"> · {a.at}</span>}
              </p>
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  )
}
