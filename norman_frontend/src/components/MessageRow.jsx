import { useRef, useEffect } from 'react'
import { marked } from 'marked'
import { renderCharts } from '../lib/charts'

marked.setOptions({ gfm: true, breaks: true })

// Custom renderer: convert ```chart blocks into placeholder divs for Chart.js
const renderer = new marked.Renderer()
const originalCode = renderer.code.bind(renderer)
renderer.code = function (token) {
  if (token.lang === 'chart') {
    // Encode spec as data attribute so renderCharts can pick it up
    const encoded = token.text.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    return `<div class="chart-placeholder" data-chart-spec="${encoded}"></div>`
  }
  return originalCode(token)
}
marked.use({ renderer })

export default function MessageRow({ role, content }) {
  const bodyRef = useRef(null)

  useEffect(() => {
    if (role === 'agent' && bodyRef.current) {
      renderCharts(bodyRef.current)
    }
  }, [role, content])

  const isAgent = role === 'agent'
  const isError = role === 'error'

  return (
    <div className="message-row">
      <div className={`message-avatar ${isAgent || isError ? 'avatar-agent' : 'avatar-user'}`}>
        {isAgent || isError ? 'N' : 'You'}
      </div>
      <div className="message-content">
        <div className={`message-sender ${isAgent ? 'agent' : 'user'}`}>
          {isAgent ? 'Norman' : isError ? 'Error' : 'You'}
        </div>
        {isAgent ? (
          <div
            ref={bodyRef}
            className="message-body"
            dangerouslySetInnerHTML={{ __html: marked.parse(content || '') }}
          />
        ) : (
          <div className={`message-body ${isError ? 'error-text' : ''}`}>
            {content}
          </div>
        )}
      </div>
    </div>
  )
}
