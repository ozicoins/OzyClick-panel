import type { ReactNode, HTMLAttributes } from 'react'

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  hover?: boolean
}

export default function GlassCard({ children, hover = true, className = '', ...rest }: Props) {
  return (
    <div
      className={`glass-card above-texture animate-fade-up ${hover ? 'glass-card-hover' : ''} p-5 ${className}`}
      {...rest}
    >
      {children}
    </div>
  )
}
