import { useEffect, useState } from 'react'
import { Menu, X } from 'lucide-react'
import Logo from '../ui/Logo'
import { ButtonLink } from '../ui/Button'
import { GITHUB_URL } from '../../lib/links'

const LINKS = [
  { href: '#how', label: 'How it works' },
  { href: '#verified', label: 'Verified' },
  { href: '#results', label: 'Results' },
  { href: '#tech', label: 'Tech' },
  { href: '#faq', label: 'FAQ' },
  { href: GITHUB_URL, label: 'GitHub' },
]

/** Sticky landing nav: blurs and shrinks once the page scrolls. */
/** `light`: the page below the hero is light, so the nav switches to the light tokens. */
export default function Nav({ light = false }: { light?: boolean }) {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,border-color,padding] duration-300 ease-(--ease-out) ${light ? 'theme-light' : ''} ${
        scrolled || open ? 'border-b border-line bg-bg/75 py-2.5 backdrop-blur-md' : 'border-b border-transparent py-4'
      }`}
    >
      <a
        href="#main"
        className="sr-only rounded-full bg-accent px-4 py-2 font-semibold text-on-accent focus:not-sr-only focus:absolute focus:top-3 focus:left-4"
      >
        Skip to content
      </a>
      <nav aria-label="Main" className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <Logo />
        <ul className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <li key={l.href}>
              <a
                href={l.href}
                className="rounded-full px-3.5 py-2 text-sm font-medium text-muted transition-colors hover:text-text"
                {...(l.href.startsWith('http') ? { target: '_blank', rel: 'noreferrer' } : {})}
              >
                {l.label}
              </a>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-2">
          <ButtonLink to="/app" size="sm">
            Open the demo
          </ButtonLink>
          <button
            type="button"
            className="grid size-9 place-items-center rounded-full border border-line text-text md:hidden"
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? 'Close menu' : 'Open menu'}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X className="size-4" aria-hidden="true" /> : <Menu className="size-4" aria-hidden="true" />}
          </button>
        </div>
      </nav>
      {open && (
        <ul id="mobile-menu" className="mx-auto flex max-w-7xl flex-col gap-1 px-4 pt-3 pb-2 md:hidden">
          {LINKS.map((l) => (
            <li key={l.href}>
              <a
                href={l.href}
                onClick={() => setOpen(false)}
                className="block rounded-xl px-3 py-2.5 text-base font-medium text-text hover:bg-surface-2"
                {...(l.href.startsWith('http') ? { target: '_blank', rel: 'noreferrer' } : {})}
              >
                {l.label}
              </a>
            </li>
          ))}
        </ul>
      )}
    </header>
  )
}
