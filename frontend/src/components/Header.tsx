import { useSystemHealth } from '../hooks/useHealth'
import { LogOut, Cpu, MemoryStick, HardDrive, Settings as SettingsIcon } from 'lucide-react'
import OzyLogo from './ui/OzyLogo'

interface Props {
  onLogout: () => void
  onOpenSettings?: () => void
}

// Canlı kaynak göstergesi — ikon + % + renkli bar (yeşil<70, amber<90, kırmızı≥90).
function ResMeter({ icon: Icon, label, pct, sub }: { icon: any; label: string; pct?: number; sub?: string }) {
  const v = Math.max(0, Math.min(100, Math.round(pct ?? 0)))
  const has = typeof pct === 'number'
  const color = v >= 90 ? '#ff4d4d' : v >= 70 ? '#f5b544' : '#2ee66b'
  return (
    <div className="flex items-center gap-2" title={`${label}${sub ? ' · ' + sub : ''}`}>
      <Icon className="w-3.5 h-3.5 flex-shrink-0" style={{ color }} aria-hidden="true" />
      <div className="min-w-0">
        <div className="flex items-baseline gap-1">
          <span className="text-[10px] uppercase tracking-wider text-slate-500 mono-font hidden md:inline">{label}</span>
          <span className="text-xs font-bold mono-font tabular-nums" style={{ color }}>{has ? v + '%' : '—'}</span>
        </div>
        <div className="h-1 w-14 sm:w-16 rounded-full bg-white/8 overflow-hidden mt-0.5">
          <div className="h-full rounded-full transition-all duration-500" style={{ width: `${has ? v : 0}%`, background: color }} />
        </div>
      </div>
    </div>
  )
}

export default function Header({ onLogout, onOpenSettings }: Props) {
  const { data: health } = useSystemHealth()
  const diskPct = health?.disk_percent

  return (
    <header className="glass-card above-texture animate-fade-up px-4 py-3 sm:px-6 sm:py-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="grid place-items-center w-10 h-10 sm:w-11 sm:h-11 rounded-2xl bg-gradient-to-br from-iuGold/30 via-iuGold/10 to-transparent border border-iuGold/25 text-iuGold shadow-gold flex-shrink-0">
          <OzyLogo size={26} className="sm:hidden" />
          <OzyLogo size={30} className="hidden sm:block" />
        </span>
        <div>
          <h1 className="heading-font text-base sm:text-xl font-extrabold text-gradient-gold leading-tight">
            OzyClick
          </h1>
          <p className="text-[10px] text-slate-400 tracking-[0.2em] uppercase mono-font">
            Cookie Generator · hit-bot
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 sm:gap-5 w-full sm:w-auto justify-between sm:justify-end">
        {/* CANLI KAYNAK GÖSTERGELERİ — RAM / CPU / Disk (4sn'de bir güncellenir) */}
        <div className="flex items-center gap-3 sm:gap-4 px-2.5 py-1.5 rounded-xl bg-iuNavy/40 border border-iuBorder">
          <ResMeter icon={Cpu} label="CPU" pct={health?.cpu_percent} sub={health?.cpu_count ? `${health.cpu_count} çekirdek` : undefined} />
          <ResMeter icon={MemoryStick} label="RAM" pct={health?.ram_percent} sub={health?.ram_used_mb ? `${health.ram_used_mb}/${health.ram_total_mb} MB` : undefined} />
          <ResMeter icon={HardDrive} label="Disk" pct={diskPct} sub={health?.disk_free_gb != null ? `${health.disk_free_gb} GB boş` : undefined} />
        </div>

        <button
          onClick={onOpenSettings}
          className="p-2 rounded-lg hover:bg-white/5 text-slate-400 hover:text-iuGold transition-colors flex-shrink-0"
          aria-label="Kullanıcı ayarları"
          title="Kullanıcı Ayarları (Telegram · şifre)"
        >
          <SettingsIcon className="w-4 h-4" />
        </button>
        <button
          onClick={onLogout}
          className="p-2 rounded-lg hover:bg-white/5 text-slate-400 hover:text-iuGold transition-colors flex-shrink-0"
          aria-label="Çıkış yap"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  )
}
