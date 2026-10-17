export type Variant = 'primary' | 'ghost' | 'subtle'

const base =
  'inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-[background-color,color,border-color,transform] duration-200 ease-(--ease-out) disabled:cursor-not-allowed disabled:opacity-50'
const variants: Record<Variant, string> = {
  primary: 'bg-accent text-on-accent hover:bg-[#d6ff5c] glow-accent',
  ghost: 'border border-line text-text hover:border-muted hover:bg-surface-2',
  subtle: 'bg-surface-2 text-text hover:bg-line',
}
export const sizes = { md: 'h-11 px-5 text-[15px]', sm: 'h-9 px-4 text-sm', lg: 'h-13 px-7 text-base' }

export function buttonClass(variant: Variant = 'primary', size: keyof typeof sizes = 'md', extra = '') {
  return `${base} ${variants[variant]} ${sizes[size]} ${extra}`
}

