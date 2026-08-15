/** Design tokens from the Stitch spec.
 *
 *  Colours resolve from CSS variables (defined per theme in index.css) so the
 *  light palette matches Stitch exactly while a dark theme stays possible
 *  without a second set of class names.
 */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'surface-bg': token('surface-bg'),
        surface: token('surface'),
        'surface-container-lowest': token('surface-container-lowest'),
        'surface-container-low': token('surface-container-low'),
        'surface-container': token('surface-container'),
        'surface-container-high': token('surface-container-high'),
        'surface-variant': token('surface-variant'),

        subtle: token('border-subtle'),
        'outline-variant': token('outline-variant'),
        outline: token('outline'),

        primary: token('primary'),
        'on-primary': token('on-primary'),
        'primary-container': token('primary-container'),
        'on-primary-container': token('on-primary-container'),
        'primary-fixed': token('primary-fixed'),

        secondary: token('secondary'),
        'secondary-container': token('secondary-container'),
        'on-secondary-container': token('on-secondary-container'),

        'on-surface': token('on-surface'),
        'on-surface-variant': token('on-surface-variant'),
        'on-background': token('on-surface'),

        'data-indigo': token('data-indigo'),
        'data-amber': token('data-amber'),
        'sql-syntax-string': token('sql-syntax-string'),
        'sql-syntax-keyword': token('sql-syntax-keyword'),

        error: token('error'),
        'error-container': token('error-container'),
        success: token('sql-syntax-string'),
        'success-container': token('success-container'),
        info: token('data-indigo'),
        'info-container': token('info-container'),
      },
      borderColor: {
        DEFAULT: 'rgb(var(--border-subtle))',
      },
      borderRadius: {
        DEFAULT: '0.25rem',
        md: '0.375rem',
        lg: '0.5rem',
        xl: '0.75rem',
        '2xl': '1rem',
        full: '9999px',
      },
      spacing: {
        base: '4px',
        gutter: '16px',
        'margin-mobile': '16px',
        'margin-desktop': '32px',
        sidebar: '280px',
      },
      maxWidth: {
        'container-max': '1440px',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        'headline-lg': ['30px', { lineHeight: '38px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'headline-lg-mobile': ['24px', { lineHeight: '32px', fontWeight: '700' }],
        'headline-md': ['24px', { lineHeight: '32px', letterSpacing: '-0.01em', fontWeight: '600' }],
        'headline-sm': ['16px', { lineHeight: '24px', fontWeight: '600' }],
        'body-lg': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'body-md': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'label-md': ['12px', { lineHeight: '16px', letterSpacing: '0.05em', fontWeight: '600' }],
        'code-sm': ['13px', { lineHeight: '20px', fontWeight: '400' }],
      },
      boxShadow: {
        card: '0px 4px 12px rgba(15, 23, 42, 0.02)',
        'card-hover': '0px 4px 12px rgba(15, 23, 42, 0.05)',
        lift: '0px 12px 32px rgba(15, 23, 42, 0.12)',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0', transform: 'translateY(5px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-in': 'fadeIn 0.15s ease-in forwards',
      },
    },
  },
  plugins: [],
}
