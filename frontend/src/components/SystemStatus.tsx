import { useQuery } from '@tanstack/react-query'
import { useSystemHealthDetailed } from '../hooks/useHealth'
import { HardDrive, Chrome, Database, Bell } from 'lucide-react'
import { api } from '../api/client'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'
import Skeleton from './ui/Skeleton'

export default function SystemStatus() {
  const { data, isLoading } = useSystemHealthDetailed()
  // Gerçek Telegram durumu (aynı query key → UserSettings kaydedince burası da tazelenir).
  const { data: tg } = useQuery({ queryKey: ['telegram-settings'], queryFn: () => api.getTelegram() })
  const tgStatus = !tg?.configured
    ? { text: 'Yapılandırılmadı', cls: 'text-slate-500' }
    : !tg?.chat_id
    ? { text: 'chat_id eksik', cls: 'text-amber-400' }
    : !tg?.enabled
    ? { text: 'Kapalı', cls: 'text-amber-400' }
    : { text: 'Açık ✓', cls: 'text-emerald-400' }

  if (isLoading) {
    return (
      <GlassCard className="space-y-3">
        <PanelHeader icon={HardDrive} title="Sistem Durumu" />
        <Skeleton rows={4} />
      </GlassCard>
    )
  }

  const diskPercent = data?.disk?.percent_used ?? 0
  const diskFree = data?.disk?.free_gb ?? 0
  const diskTotal = data?.disk?.total_gb ?? 0
  const redisConnected = data?.redis?.connected ?? false
  const redisMem = data?.redis?.used_memory_mb ?? 0
  const redisKeys = data?.redis?.keys ?? 0
  const chromeTotal = data?.chrome_pool?.total ?? 0
  const chromeActive = data?.chrome_pool?.active ?? 0
  const chromeZombies = data?.chrome_pool?.zombies ?? 0

  return (
    <GlassCard className="space-y-3">
      <PanelHeader icon={HardDrive} title="Sistem Durumu" />

      <div className="space-y-3">
        <div>
          <div className="flex justify-between text-[10px] text-slate-500 mb-1">
            <span>Disk Kullanımı</span>
            <span>{diskFree} GB boş / {diskTotal} GB</span>
          </div>
          <div className="w-full h-2 bg-iuNavy/50 rounded-full overflow-hidden" role="progressbar" aria-valuenow={diskPercent} aria-valuemin={0} aria-valuemax={100} aria-label="Disk kullanımı">
            <div
              className={`h-full rounded-full transition-all ${
                diskPercent > 90 ? 'bg-red-500' : diskPercent > 80 ? 'bg-amber-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${Math.min(diskPercent, 100)}%` }}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="bg-iuNavy/30 rounded-lg p-2.5">
            <div className="flex items-center gap-1.5 mb-1">
              <Chrome className="w-3 h-3 text-slate-500" aria-hidden="true" />
              <span className="text-[10px] text-slate-500">Chrome Pool</span>
            </div>
            <p className="text-xs text-slate-300">{chromeActive}/{chromeTotal} ayakta</p>
            {chromeZombies > 0 && (
              <p className="text-[10px] text-amber-400">{chromeZombies} zombie</p>
            )}
          </div>

          <div className="bg-iuNavy/30 rounded-lg p-2.5">
            <div className="flex items-center gap-1.5 mb-1">
              <Database className="w-3 h-3 text-slate-500" aria-hidden="true" />
              <span className="text-[10px] text-slate-500">Redis</span>
            </div>
            <p className="text-xs">
              {redisConnected ? (
                <span className="text-emerald-400">Bağlı</span>
              ) : (
                <span className="text-red-400">Kopuk</span>
              )}
            </p>
            <p className="text-[10px] text-slate-600">{redisMem}MB / {redisKeys} key</p>
          </div>
        </div>

        <div className="bg-iuNavy/30 rounded-lg p-2.5">
          <div className="flex items-center gap-1.5 mb-1">
            <Bell className="w-3 h-3 text-slate-500" aria-hidden="true" />
            <span className="text-[10px] text-slate-500">Telegram Bildirimleri</span>
          </div>
          <p className={`text-xs ${tgStatus.cls}`}>{tgStatus.text}</p>
        </div>
      </div>
    </GlassCard>
  )
}
