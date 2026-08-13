interface Props {
  value: string | number
  label: string
  color?: 'emerald' | 'red' | 'gold' | 'amber' | 'cyan'
}

const colorMap = {
  emerald: 'text-emerald-400 bg-emerald-500/5',
  red: 'text-red-400 bg-red-500/5',
  gold: 'text-iuGold bg-iuGold/5',
  amber: 'text-amber-400 bg-amber-500/5',
  cyan: 'text-cyan-400 bg-cyan-500/5',
} as const

export default function StatBox({ value, label, color = 'gold' }: Props) {
  return (
    <div className={`${colorMap[color]} rounded-lg p-2 text-center`}>
      <p className={`text-lg font-bold ${colorMap[color].split(' ')[0]}`}>{value}</p>
      <p className="text-[10px] text-slate-500">{label}</p>
    </div>
  )
}
