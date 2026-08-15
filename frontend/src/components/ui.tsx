/** Shared primitives, styled to the Stitch design spec. */

import type { ReactNode } from 'react'

import { Icon } from '@/components/icons'

/* ------------------------------------------------------------------ button */

type Variant = 'primary' | 'outline' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-primary text-on-primary border-primary hover:bg-opacity-90',
  outline:
    'bg-surface-container-lowest text-on-surface-variant border-subtle hover:bg-surface-container-low hover:text-on-surface',
  ghost:
    'bg-transparent text-on-surface-variant border-transparent hover:bg-surface-container-low hover:text-on-surface',
  danger:
    'bg-transparent text-error border-transparent hover:bg-error-container hover:text-error',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 gap-1.5',
  md: 'h-10 px-4 gap-2',
}

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  busy?: boolean
  icon?: string
}

export function Button({
  variant = 'outline',
  size = 'md',
  busy,
  icon,
  children,
  className = '',
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      disabled={disabled || busy}
      className={`inline-flex items-center justify-center whitespace-nowrap rounded-lg border text-label-md transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...props}
    >
      {busy ? <Spinner /> : icon && <Icon name={icon} size={18} />}
      {children}
    </button>
  )
}

export function IconButton({
  icon,
  label,
  onClick,
  fill,
  className = '',
}: {
  icon: string
  label: string
  onClick: () => void
  fill?: boolean
  className?: string
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      className={`flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-container-low hover:text-on-surface ${className}`}
    >
      <Icon name={icon} size={20} fill={fill} />
    </button>
  )
}

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`h-4 w-4 shrink-0 animate-spin ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

/* --------------------------------------------------------------------- pill */

type Tone = 'neutral' | 'online' | 'offline' | 'pending' | 'indigo' | 'amber'

const TONES: Record<Tone, { chip: string; dot: string }> = {
  neutral: { chip: 'bg-surface-variant text-on-surface-variant', dot: 'bg-outline' },
  online: { chip: 'bg-success-container text-sql-syntax-string', dot: 'bg-sql-syntax-string' },
  offline: { chip: 'bg-error-container text-error', dot: 'bg-error' },
  pending: { chip: 'bg-surface-container-high text-on-surface-variant', dot: 'bg-outline' },
  indigo: { chip: 'bg-secondary-container text-on-secondary-container', dot: 'bg-data-indigo' },
  amber: { chip: 'bg-data-amber/10 text-data-amber', dot: 'bg-data-amber' },
}

export function Pill({
  tone = 'neutral',
  dot = true,
  children,
  className = '',
}: {
  tone?: Tone
  dot?: boolean
  children: ReactNode
  className?: string
}) {
  const style = TONES[tone]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-label-md ${style.chip} ${className}`}
    >
      {dot && <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${style.dot}`} />}
      {children}
    </span>
  )
}

/** Small monospace tag, for identifiers and annotations inside tables. */
export function Tag({
  tone = 'neutral',
  children,
}: {
  tone?: Tone
  children: ReactNode
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px] leading-4 ${TONES[tone].chip}`}
    >
      {children}
    </span>
  )
}

/* -------------------------------------------------------------------- form */

export function Field({
  label,
  hint,
  children,
  className = '',
}: {
  label: string
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1.5 block text-label-md text-on-surface-variant">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-body-md text-outline">{hint}</span>}
    </label>
  )
}

const CONTROL =
  'w-full rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md text-on-surface placeholder:text-outline transition-shadow focus:border-data-indigo focus:outline-none focus:ring-1 focus:ring-data-indigo'

export function Input({
  className = '',
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${CONTROL} ${className}`} {...props} />
}

export function Select({
  className = '',
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`${CONTROL} ${className}`} {...props} />
}

export function SearchInput({
  icon = 'search',
  className = '',
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { icon?: string }) {
  return (
    <div className="relative w-full">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant">
        <Icon name={icon} size={18} />
      </span>
      <input
        className={`w-full rounded-md border border-outline-variant bg-surface-container-low py-2 pl-10 pr-3 text-body-md text-on-surface placeholder:text-outline transition-shadow focus:border-data-indigo focus:outline-none focus:ring-1 focus:ring-data-indigo ${className}`}
        {...props}
      />
    </div>
  )
}

/* ---------------------------------------------------------------- feedback */

export function Alert({ children }: { children: ReactNode }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-error/20 bg-error-container px-3 py-2.5 text-body-md text-error"
    >
      <Icon name="error" size={18} className="mt-px" />
      <span className="min-w-0 break-words">{children}</span>
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-container-high ${className}`} />
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: string
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="col-span-full flex flex-col items-center rounded-xl border-2 border-dashed border-subtle px-6 py-16 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-surface-container-low text-on-surface-variant">
        <Icon name={icon} size={24} />
      </div>
      <h3 className="text-headline-sm text-primary">{title}</h3>
      <p className="mt-1 max-w-sm text-body-md text-on-surface-variant">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
