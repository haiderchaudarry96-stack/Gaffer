import { LogoMark } from '../ui/Logo'
import { COMPETITION_URL, GITHUB_URL, TEAMTRACK_URL } from '../../lib/links'

const ext = { target: '_blank', rel: 'noreferrer' } as const
const linkCls = 'underline decoration-line underline-offset-4 hover:text-text hover:decoration-muted'

export default function Footer() {
  return (
    <footer className="border-t border-line bg-bg">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.2fr_1fr_1fr]">
        <div className="space-y-3">
          <div className="flex items-center gap-2.5">
            <LogoMark />
            <span className="font-display text-lg font-bold">Gaffer</span>
          </div>
          <p className="max-w-xs text-sm text-muted">Your tactical analyst. It watches, checks, then tells you.</p>
          <p className="text-sm text-muted">
            Built for the{' '}
            <a href={COMPETITION_URL} className={linkCls} {...ext}>
              OpenCV AI Competition 2026, powered by AWS
            </a>
            . Code under the MIT licence on{' '}
            <a href={GITHUB_URL} className={linkCls} {...ext}>
              GitHub
            </a>
            .
          </p>
        </div>
        <div>
          <h2 className="mb-3 font-sans text-sm font-semibold tracking-normal text-text">Data</h2>
          <p className="text-sm text-muted">
            Match footage and positions:{' '}
            <a href={TEAMTRACK_URL} className={linkCls} {...ext}>
              TeamTrack
            </a>{' '}
            — Scott et al., “TeamTrack: A Dataset for Multi-Sport Multi-Object Tracking in Full-pitch Videos”, 2024. MIT
            licence.
          </p>
          <p className="mt-3 text-sm text-muted">
            Positions on this site are Gaffer’s own OpenCV 5 pipeline output for that footage; no video is served here.
          </p>
        </div>
        <div>
          <h2 className="mb-3 font-sans text-sm font-semibold tracking-normal text-text">Built with</h2>
          <ul className="space-y-1.5 text-sm text-muted">
            <li>OpenCV 5 — Apache 2.0</li>
            <li>Amazon Nova 2 Lite on Amazon Bedrock</li>
            <li>React, Vite, Tailwind CSS, Motion — MIT</li>
            <li>Lucide icons — ISC</li>
            <li>Space Grotesk, Inter, JetBrains Mono — SIL OFL 1.1</li>
          </ul>
        </div>
      </div>
    </footer>
  )
}
