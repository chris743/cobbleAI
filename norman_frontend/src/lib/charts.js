import Chart from 'chart.js/auto'

const CHART_PALETTE = [
  'rgba(30, 75, 50, 0.75)',
  'rgba(218, 118, 45, 0.75)',
  'rgba(16, 185, 129, 0.7)',
  'rgba(245, 158, 11, 0.7)',
  'rgba(59, 130, 246, 0.7)',
  'rgba(139, 92, 246, 0.7)',
  'rgba(6, 182, 212, 0.7)',
  'rgba(156, 163, 175, 0.7)',
]
const CHART_BORDERS = CHART_PALETTE.map((c) => c.replace('0.7)', '1)'))

/**
 * Find ```chart code blocks in a container element and render Chart.js canvases.
 */
export function renderCharts(container) {
  const codeBlocks = container.querySelectorAll('code.language-chart')
  codeBlocks.forEach((code) => {
    const pre = code.parentElement
    try {
      const spec = JSON.parse(code.textContent)
      const wrapper = document.createElement('div')
      wrapper.className = 'chart-container'

      if (spec.title) {
        const title = document.createElement('div')
        title.className = 'chart-title'
        title.textContent = spec.title
        wrapper.appendChild(title)
      }

      const canvas = document.createElement('canvas')
      wrapper.appendChild(canvas)
      pre.replaceWith(wrapper)

      let chartType = spec.type === 'horizontalBar' ? 'bar' : spec.type
      const datasets = (spec.datasets || []).map((ds, i) => ({
        label: ds.label || `Series ${i + 1}`,
        data: ds.data,
        backgroundColor:
          ds.backgroundColor ||
          (['pie', 'doughnut'].includes(chartType)
            ? CHART_PALETTE.slice(0, ds.data.length)
            : CHART_PALETTE[i % CHART_PALETTE.length]),
        borderColor:
          ds.borderColor ||
          (['pie', 'doughnut'].includes(chartType)
            ? CHART_BORDERS.slice(0, ds.data.length)
            : CHART_BORDERS[i % CHART_BORDERS.length]),
        borderWidth: ds.borderWidth || (chartType === 'line' ? 2 : 1),
        tension: chartType === 'line' ? 0.3 : undefined,
        fill: chartType === 'line' ? false : undefined,
      }))

      const indexAxis =
        spec.indexAxis || (spec.type === 'horizontalBar' ? 'y' : undefined)

      new Chart(canvas, {
        type: chartType,
        data: { labels: spec.labels || [], datasets },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          indexAxis,
          plugins: {
            legend: {
              display:
                datasets.length > 1 ||
                ['pie', 'doughnut'].includes(chartType),
            },
            title: { display: false },
          },
          scales: ['pie', 'doughnut'].includes(chartType)
            ? {}
            : { y: { beginAtZero: true } },
        },
      })
    } catch (e) {
      console.warn('Chart render failed:', e)
    }
  })
}
