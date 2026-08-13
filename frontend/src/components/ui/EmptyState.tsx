import type { LucideIcon } from 'lucide-react'

interface Props {
  icon?: LucideIcon
  message: string
  description?: string
}

export default function EmptyState({ icon: Icon, message, description }: Props) {
  return (
    <div role="status" className="flex flex-col items-center justify-center py-8 gap-2">
      {Icon && <Icon className="w-8 h-8 text-slate-600" aria-hidden="true" />}
      <p className="text-xs text-slate-500">{message}</p>
      {description && <p className="text-[10px] text-slate-600">{description}</p>}
    </div>
  )
}
