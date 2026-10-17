import { Link } from 'react-router-dom'

/** Gaffer wordmark: a tiny pitch with a lime dot that "checks" the shape. */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="var(--surface-2)" />
      <rect x="5.5" y="8.5" width="21" height="15" rx="1.5" fill="none" stroke="var(--muted)" strokeOpacity=".55" />
      <line x1="16" y1="8.5" x2="16" y2="23.5" stroke="var(--muted)" strokeOpacity=".55" />
      <circle cx="11" cy="13" r="2" fill="var(--team-a)" />
      <circle cx="11" cy="19" r="2" fill="var(--team-a)" />
      <circle cx="21.5" cy="16" r="2.6" fill="var(--accent)" />
    </svg>
  )
}

export default function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-lg" aria-label="Gaffer home">
      <LogoMark />
      <span className="font-display text-xl font-bold tracking-tight text-text">Gaffer</span>
    </Link>
  )
}
