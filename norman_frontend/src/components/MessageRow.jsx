import { useRef, useEffect } from 'react'
import { marked } from 'marked'
import { renderCharts } from '../lib/charts'

marked.setOptions({ gfm: true, breaks: true })

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
