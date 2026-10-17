import { useId } from 'react'

/**
 * Gaffer's agent mascot: an original flat drawing. A robot whose head is a black-and-white
 * football with a dark glossy visor, two cyan eyes and a small smile, a silver headset with a
 * microphone, and green jersey shoulders with navy trim and an "AI" badge.
 * Eyes blink every ~6 s (CSS, `.mascot-eyes` in index.css), never with reduced motion.
 */
export default function Mascot({
  size = 56,
  title,
  blink = true,
  className = '',
}: {
  size?: number
  /** accessible name; omit when the mascot is decoration next to visible text */
  title?: string
  blink?: boolean
  className?: string
}) {
  const id = useId().replace(/:/g, '')
  const clip = `ball-${id}`
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 128 128"
      className={className}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <clipPath id={clip}>
          <circle cx="64" cy="52" r="37" />
        </clipPath>
      </defs>

      {/* shoulders: green jersey, navy collar trim */}
      <path d="M14 128 C14 104 32 92 52 90 L76 90 C96 92 114 104 114 128 Z" fill="#1E9E57" />
      <path d="M52 90 L64 104 L76 90" fill="none" stroke="#14213D" strokeWidth="6" strokeLinejoin="round" />
      <path d="M14 128 C14 112 20 103 28 98" fill="none" stroke="#14213D" strokeWidth="5" strokeLinecap="round" />
      <path d="M114 128 C114 112 108 103 100 98" fill="none" stroke="#14213D" strokeWidth="5" strokeLinecap="round" />
      {/* AI badge */}
      <rect x="80" y="106" width="20" height="13" rx="3.5" fill="#14213D" />
      <text x="90" y="116" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif" fontSize="9.5" fontWeight="800" fill="#FFFFFF">
        AI
      </text>
      {/* neck */}
      <rect x="56" y="84" width="16" height="9" rx="3" fill="#14213D" />

      {/* head: classic football */}
      <circle cx="64" cy="52" r="37" fill="#F6F7F2" />
      <g clipPath={`url(#${clip})`} fill="#1B1F24">
        <path d="M64 8 L75 16 L71 29 L57 29 L53 16 Z" />
        <path d="M24 34 L35 32 L40 44 L32 54 L22 49 Z" />
        <path d="M104 34 L93 32 L88 44 L96 54 L106 49 Z" />
        <path d="M37 79 L44 70 L56 74 L56 86 L42 90 Z" />
        <path d="M91 79 L84 70 L72 74 L72 86 L86 90 Z" />
      </g>
      <g clipPath={`url(#${clip})`} fill="none" stroke="#1B1F24" strokeWidth="1.6" strokeLinecap="round">
        <path d="M57 29 L40 44 M71 29 L88 44 M32 54 L44 70 M96 54 L84 70 M56 86 L72 86" />
      </g>
      <circle cx="64" cy="52" r="37" fill="none" stroke="#1B1F24" strokeWidth="2.5" />

      {/* visor */}
      <rect x="36" y="40" width="56" height="30" rx="15" fill="#0D1B26" />
      <path d="M44 45 C52 42 64 42 72 43" fill="none" stroke="#FFFFFF" strokeOpacity="0.35" strokeWidth="3" strokeLinecap="round" />
      {/* eyes and smile */}
      <g className={blink ? 'mascot-eyes' : undefined}>
        <circle cx="53" cy="55" r="8" fill="#38E1FF" opacity="0.22" />
        <circle cx="75" cy="55" r="8" fill="#38E1FF" opacity="0.22" />
        <ellipse cx="53" cy="55" rx="4.5" ry="5.5" fill="#5BEAFF" />
        <ellipse cx="75" cy="55" rx="4.5" ry="5.5" fill="#5BEAFF" />
      </g>
      <path d="M58 64 Q64 68.5 70 64" fill="none" stroke="#5BEAFF" strokeWidth="2.6" strokeLinecap="round" />

      {/* headset: band, ear cups, microphone */}
      <path d="M25 50 A39 39 0 0 1 103 50" fill="none" stroke="#C3CCD5" strokeWidth="5" strokeLinecap="round" />
      <rect x="17" y="42" width="13" height="23" rx="5" fill="#C3CCD5" />
      <rect x="21" y="46" width="5" height="15" rx="2.5" fill="#7D8995" />
      <rect x="98" y="42" width="13" height="23" rx="5" fill="#C3CCD5" />
      <rect x="102" y="46" width="5" height="15" rx="2.5" fill="#7D8995" />
      <path d="M24 64 C24 76 32 80 44 79" fill="none" stroke="#C3CCD5" strokeWidth="3.5" strokeLinecap="round" />
      <rect x="43" y="75" width="8" height="7" rx="3" fill="#2B3138" />
    </svg>
  )
}
