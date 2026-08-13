import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Network } from 'lucide-react'
import type { ProxyMapEntry } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'
import EmptyState from './ui/EmptyState'
import Skeleton from './ui/Skeleton'

interface Props {
  email: string
}

export default function ProxyMapTable({ email }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['proxy-map', email],
    queryFn: () => api.getProxyMap(email),
    enabled: !!email,
  })

  const entries: ProxyMapEntry[] = Array.isArray(data) ? data : []

  return (
    <GlassCard className="space-y-3">
      <PanelHeader icon={Network} title="Proxy-Cookie Eşleştirme" />

      {!email ? (
        <EmptyState icon={Network} message="Hesap seçin" />
      ) : isLoading ? (
        <Skeleton rows={4} />
      ) : entries.length === 0 ? (
        <EmptyState icon={Network} message="Proxy verisi yok" />
      ) : (
        <div className="overflow-x-auto max-h-52 overflow-y-auto -mx-5 px-5">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-iuCard">
              <tr className="text-left text-slate-500 border-b border-iuBorder">
                <th className="pb-2 pr-2">Profil</th>
                <th className="pb-2 pr-2">Proxy IP</th>
                <th className="pb-2 pr-2 hidden sm:table-cell">Tip</th>
                <th className="pb-2">Durum</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, i) => (
                <tr key={i} className="border-b border-iuBorder/20 hover:bg-white/[0.02]">
                  <td className="py-1.5 pr-2 text-slate-300 max-w-[100px] truncate">{entry.profileFile}</td>
                  <td className="py-1.5 pr-2 text-slate-400 font-mono max-w-[120px] truncate">{entry.assignedProxy}</td>
                  <td className="py-1.5 pr-2 hidden sm:table-cell">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                      entry.proxyType === 'IPv6' ? 'bg-purple-500/10 text-purple-400' : 'bg-blue-500/10 text-blue-400'
                    }`}>
                      {entry.proxyType}
                    </span>
                  </td>
                  <td className="py-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full inline-block ${
                        entry.status === 'ACTIVE' ? 'bg-emerald-400' : 'bg-red-500'
                      }`}
                      role="status"
                      aria-label={entry.status === 'ACTIVE' ? 'Aktif' : 'Pasif'}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassCard>
  )
}
