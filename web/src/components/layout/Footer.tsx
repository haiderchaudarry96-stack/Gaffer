import { LogoMark } from '../ui/Logo'
import { AUTHOR_URL, TEAMTRACK_URL } from '../../lib/links'

const linkCls = 'underline decoration-line underline-offset-4 hover:text-text hover:decoration-muted'

export default function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.2fr_0.7fr_1fr]">
        <div className="space-y-3">
          <div className="flex items-center gap-2.5"><LogoMark /><span className="font-display text-lg font-bold">Gaffer</span></div>
          <p className="max-w-sm text-sm text-muted">A clearer view of team shape. Evidence for your next coaching conversation.</p>
          <p className="max-w-sm text-sm text-muted">An early football video analysis product for recorded match review.</p>
        </div>
        <nav aria-label="Footer">
          <h2 className="mb-3 font-sans text-sm font-semibold tracking-normal text-text">Explore</h2>
          <ul className="space-y-2 text-sm text-muted">
            <li><a href="#product" className={linkCls}>Product</a></li>
            <li><a href="#features" className={linkCls}>Features</a></li>
            <li><a href="#demo" className={linkCls}>Recorded demo</a></li>
            <li><a href="#faq" className={linkCls}>FAQ</a></li>
          </ul>
        </nav>
        <div>
          <h2 className="mb-3 font-sans text-sm font-semibold tracking-normal text-text">Footage credits</h2>
          <p className="text-sm text-muted">Example footage: <a href={TEAMTRACK_URL} className={linkCls} target="_blank" rel="noreferrer">TeamTrack</a>, Scott et al., 2024. MIT licence.</p>
          <p className="mt-3 text-sm text-muted">The example uses recorded footage and estimated positions. It is not a live camera feed.</p>
        </div>
      </div>
      <div className="mx-auto max-w-7xl border-t border-line px-4 py-5 sm:px-6">
        <p className="text-xs text-muted">Designed &amp; built by <a href={AUTHOR_URL} target="_blank" rel="noopener" className="font-medium text-accent-ink underline-offset-4 hover:underline">Haider Sultan</a> · FAST-NUCES, Pakistan</p>
      </div>
    </footer>
  )
}
