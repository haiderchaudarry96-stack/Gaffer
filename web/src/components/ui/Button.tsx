import type { ComponentProps, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { buttonClass, type sizes, type Variant } from './buttonStyles'

export function ButtonLink({
  to,
  variant,
  size,
  children,
  className = '',
}: {
  to: string
  variant?: Variant
  size?: keyof typeof sizes
  children: ReactNode
  className?: string
}) {
  const cls = buttonClass(variant, size, className)
  if (to.startsWith('#') || to.startsWith('http')) {
    return (
      <a href={to} className={cls} {...(to.startsWith('http') ? { target: '_blank', rel: 'noreferrer' } : {})}>
        {children}
      </a>
    )
  }
  return (
    <Link to={to} className={cls}>
      {children}
    </Link>
  )
}

export function Button({
  variant,
  size,
  className = '',
  ...rest
}: ComponentProps<'button'> & { variant?: Variant; size?: keyof typeof sizes }) {
  return <button type="button" className={buttonClass(variant, size, className)} {...rest} />
}
