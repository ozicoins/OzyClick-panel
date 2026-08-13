// OzyClick özel logo işareti — hedef nişangahı (O / target) + tık imleci (click).
// currentColor'ı miras alır → tema yeşiliyle boyanır. size prop'u px cinsinden.
export default function OzyLogo({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 44 44"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      {/* dış nişangah tikleri */}
      <path
        d="M20 1.5V7 M20 33V38.5 M1.5 20H7 M33 20H38.5"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        opacity="0.75"
      />
      {/* O / hedef halkası */}
      <circle cx="20" cy="20" r="14" stroke="currentColor" strokeWidth="3" />
      {/* bullseye */}
      <circle cx="20" cy="20" r="5" fill="currentColor" />
      {/* tık imleci (sağ-alttan çıkan cursor) */}
      <path
        d="M25.5 25.5 L41 32 L33.8 34.4 L37.6 41 L34.2 43 L30.4 36.4 L24.8 40.5 Z"
        fill="currentColor"
        stroke="#06110b"
        strokeWidth="1"
        strokeLinejoin="round"
      />
    </svg>
  )
}
