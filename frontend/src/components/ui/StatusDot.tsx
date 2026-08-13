interface Props {
  active: boolean
  label: string
  pulse?: boolean
}

export default function StatusDot({ active, label, pulse = true }: Props) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span
        className={`w-2 h-2 rounded-full ${
          active ? `bg-emerald-400 ${pulse ? 'pulse-dot' : ''}` : 'bg-red-500'
        }`}
        role="status"
        aria-label={`${label}: ${active ? 'aktif' : 'pasif'}`}
      />
      <span className="text-slate-400">{label}</span>
    </div>
  )
}
