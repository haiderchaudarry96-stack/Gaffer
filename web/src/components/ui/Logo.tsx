import { Link } from 'react-router-dom'

/**
 * Gaffer mark: a tactics board (pitch, halfway line, three players) with a lime check on it,
 * the product in one picture: a shape that has been checked. Same drawing as `public/favicon.svg`.
 */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="#070D0A" />
      <rect x="9" y="12" width="46" height="40" rx="4" fill="#16231C" stroke="#8FA398" strokeWidth="3" />
      <line x1="32" y1="12" x2="32" y2="52" stroke="#8FA398" strokeWidth="2.2" />
      <circle cx="19" cy="23" r="4.2" fill="#FF5B4F" />
      <circle cx="19" cy="41" r="4.2" fill="#FF5B4F" />
      <circle cx="45" cy="23" r="4.2" fill="#44C8FF" />
      <path d="M30 41 L38 49 L56 30" fill="none" stroke="#070D0A" strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M30 41 L38 49 L56 30" fill="none" stroke="#C8F542" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
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
