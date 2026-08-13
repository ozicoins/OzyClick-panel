interface Props {
  rows?: number
  className?: string
}

export default function Skeleton({ rows = 3, className = '' }: Props) {
  return (
    <div className={`space-y-2 ${className}`} aria-busy="true" aria-label="Yükleniyor">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-8 bg-iuNavy/40 animate-pulse rounded-lg"
          style={{ width: `${100 - i * 10}%` }}
        />
      ))}
    </div>
  )
}
