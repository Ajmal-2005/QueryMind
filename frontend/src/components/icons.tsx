/** Material Symbols, as used throughout the design.
 *
 *  The variable font is loaded once in index.html; a symbol is just its name
 *  as text content, so there is no icon package and no per-icon module.
 */

interface IconProps {
  name: string
  /** Pixel size. Material Symbols are sized by font-size, not width/height. */
  size?: number
  /** Use the filled variant - the design fills icons on active nav items. */
  fill?: boolean
  weight?: number
  className?: string
  title?: string
}

export function Icon({
  name,
  size = 20,
  fill = false,
  weight = 400,
  className = '',
  title,
}: IconProps) {
  return (
    <span
      className={`material-symbols-outlined shrink-0 select-none ${className}`}
      style={{
        fontSize: size,
        width: size,
        height: size,
        fontVariationSettings: `'FILL' ${fill ? 1 : 0}, 'wght' ${weight}, 'GRAD' 0, 'opsz' ${size}`,
      }}
      title={title}
      aria-hidden="true"
    >
      {name}
    </span>
  )
}
