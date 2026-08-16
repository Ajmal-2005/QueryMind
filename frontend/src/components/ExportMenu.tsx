/** Export (F17): CSV, JSON, Excel and PDF from the server; PNG in the browser.
 *
 *  PNG is the odd one out on purpose. The chart is a Recharts SVG that only
 *  exists here, so serialising it to a canvas is both exact and free. Asking
 *  the server to redraw it would mean a second charting implementation whose
 *  output could quietly disagree with what the user is looking at.
 *
 *  The PDF takes the opposite route for the same reason: the browser hands its
 *  own rendered chart up as a PNG, and the server composes the report around it.
 */

import { useState } from 'react'

import { downloadExport } from '@/api/analytics'
import { errorMessage } from '@/api/client'
import type { ExportFormat } from '@/api/types'
import { Icon } from '@/components/icons'
import { Button } from '@/components/ui'

/** Serialise a live SVG element to a PNG data URL.
 *
 *  Styles are inlined by the browser only for attributes, not CSS classes, so
 *  the chart's own stroke/fill attributes carry over but the surrounding theme
 *  does not — hence the explicit white ground, which is also what a PDF wants.
 */
async function svgToPng(svg: SVGSVGElement, scale = 2): Promise<string | null> {
  const box = svg.getBoundingClientRect()
  if (!box.width || !box.height) return null

  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('width', String(box.width))
  clone.setAttribute('height', String(box.height))
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')

  const source = new XMLSerializer().serializeToString(clone)
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`

  const image = new Image()
  image.crossOrigin = 'anonymous'

  const loaded = await new Promise<boolean>((resolve) => {
    image.onload = () => resolve(true)
    image.onerror = () => resolve(false)
    image.src = url
  })
  if (!loaded) return null

  const canvas = document.createElement('canvas')
  canvas.width = box.width * scale
  canvas.height = box.height * scale
  const context = canvas.getContext('2d')
  if (!context) return null

  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/png')
}

function saveDataUrl(dataUrl: string, filename: string): void {
  const anchor = document.createElement('a')
  anchor.href = dataUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

const FORMATS: { format: ExportFormat | 'png'; label: string; icon: string }[] = [
  { format: 'csv', label: 'CSV', icon: 'description' },
  { format: 'xlsx', label: 'Excel', icon: 'table_chart' },
  { format: 'json', label: 'JSON', icon: 'data_object' },
  { format: 'png', label: 'PNG chart', icon: 'image' },
  { format: 'pdf', label: 'PDF report', icon: 'picture_as_pdf' },
]

export function ExportMenu({
  connectionId,
  sql,
  question,
  title,
  chartRef,
  hasChart,
}: {
  connectionId: string
  sql: string
  question: string
  title: string
  chartRef: React.RefObject<HTMLDivElement | null>
  hasChart: boolean
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function chartPng(): Promise<string | null> {
    const svg = chartRef.current?.querySelector('svg')
    return svg ? svgToPng(svg as SVGSVGElement) : null
  }

  async function run(format: ExportFormat | 'png') {
    setBusy(format)
    setError(null)
    try {
      if (format === 'png') {
        const png = await chartPng()
        if (!png) throw new Error('There is no chart on screen to save.')
        saveDataUrl(png, `${title.replace(/\s+/g, '-')}.png`)
      } else {
        await downloadExport({
          connection_id: connectionId,
          sql,
          question,
          title,
          format,
          include_narrative: format === 'pdf',
          chart_png: format === 'pdf' && hasChart ? await chartPng() : null,
        })
      }
      setOpen(false)
    } catch (err) {
      setError(errorMessage(err, 'Export failed'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="relative">
      <Button
        size="sm"
        icon="download"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        Export
      </Button>

      {open && (
        <>
          {/* Click-away target, behind the menu but above the page. */}
          <button
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-40 cursor-default"
          />
          <div className="absolute right-0 z-50 mt-1 w-48 overflow-hidden rounded-lg border border-subtle bg-surface-container-lowest shadow-card">
            {FORMATS.map(({ format, label, icon }) => {
              const unavailable = format === 'png' && !hasChart
              return (
                <button
                  key={format}
                  disabled={busy !== null || unavailable}
                  onClick={() => run(format)}
                  title={unavailable ? 'This result is not drawn as a chart' : undefined}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-body-md text-on-surface-variant transition-colors hover:bg-surface-container-low hover:text-on-surface disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Icon name={busy === format ? 'hourglass_top' : icon} size={16} />
                  {label}
                </button>
              )
            })}
            {error && (
              <p className="border-t border-subtle px-3 py-2 text-[11px] text-error">
                {error}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
