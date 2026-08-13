import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

interface Props {
  icon: LucideIcon
  title: string
  actions?: ReactNode
}

export default function PanelHeader({ icon: Icon, title, actions }: Props) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="heading-font text-sm font-semibold text-slate-100 flex items-center gap-2.5">
        <span className="grid place-items-center w-7 h-7 rounded-lg bg-gradient-to-br from-iuGold/25 to-iuGold/5 border border-iuGold/20 text-iuGold shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
          <Icon className="w-3.5 h-3.5" aria-hidden="true" />
        </span>
        {title}
      </h2>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
