import { useState, useMemo } from 'react'

export default function Sidebar({
  open,
  conversations,
  activeId,
  onSelect,
  onNew,
  user,
  onSignOut,
  livingDocs,
  activeLivingDocId,
  onSelectLivingDoc,
  customerSpecs,
  onDeleteSpec,
  scheduledReportCount,
  onOpenScheduledReports,
}) {
  const [tab, setTab] = useState('chat')

  // Organize specs into tree: customer -> location -> [rules]
  const specTree = useMemo(() => {
    if (!customerSpecs || !customerSpecs.length) return {}
    const tree = {}
    customerSpecs.forEach((spec) => {
      const customer = spec.customer || 'Unknown'
      const dc = spec.dc || 'All Locations'
      if (!tree[customer]) tree[customer] = {}
      if (!tree[customer][dc]) tree[customer][dc] = []
      tree[customer][dc].push(spec)
    })
    return tree
  }, [customerSpecs])

  return (
    <aside className={`sidebar ${open ? '' : 'collapsed'}`}>
      <div className="sidebar-header">
        <div className="sidebar-logo">N</div>
        <div className="sidebar-brand">
          Norman
          <small>Powered by Cobblestone Fruit Company</small>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="sidebar-tabs">
        <button
          className={`sidebar-tab ${tab === 'chat' ? 'active' : ''}`}
          onClick={() => setTab('chat')}
        >
          Chat
        </button>
        <button
          className={`sidebar-tab ${tab === 'specs' ? 'active' : ''}`}
          onClick={() => setTab('specs')}
        >
          Customer Specs
        </button>
      </div>

      {tab === 'chat' ? (
        <>
          <button className="new-chat-btn" onClick={onNew}>
            <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New Conversation
          </button>

          {livingDocs && livingDocs.length > 0 && (
            <div className="sidebar-section">
              <div className="sidebar-section-label">Living Documents</div>
              {livingDocs.map((doc) => (
                <div
                  key={doc.id}
                  className={`convo-item living-doc-item ${doc.id === activeLivingDocId ? 'active' : ''}`}
                  onClick={() => onSelectLivingDoc(doc)}
                  title={doc.description || doc.name}
                >
                  <span className="living-doc-icon">&#x1F4CB;</span>
                  {doc.name}
                </div>
              ))}
            </div>
          )}

          <div className="sidebar-section">
            <button className="scheduled-reports-btn" onClick={onOpenScheduledReports}>
              <span className="scheduled-reports-icon">&#x1F4C5;</span>
              Scheduled Reports
              {scheduledReportCount > 0 && (
                <span className="scheduled-reports-badge">{scheduledReportCount}</span>
              )}
            </button>
          </div>

          <div className="sidebar-section">
            {(livingDocs && livingDocs.length > 0) && (
              <div className="sidebar-section-label">Conversations</div>
            )}
            <div className="conversation-list">
              {conversations.map((c) => (
                <div
                  key={c.id}
                  className={`convo-item ${c.id === activeId ? 'active' : ''}`}
                  onClick={() => onSelect(c.id)}
                >
                  {c.title}
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="sidebar-section specs-section">
          {Object.keys(specTree).length === 0 ? (
            <div className="specs-empty">
              No customer specs yet. Tell Norman about customer requirements in chat and they'll appear here.
            </div>
          ) : (
            Object.entries(specTree).sort(([a], [b]) => a.localeCompare(b)).map(([customer, locations]) => (
              <div key={customer} className="spec-customer">
                <div className="spec-customer-name">{customer}</div>
                {Object.entries(locations).sort(([a], [b]) => {
                  if (a === 'All Locations') return -1
                  if (b === 'All Locations') return 1
                  return a.localeCompare(b)
                }).map(([dc, rules]) => (
                  <div key={dc} className="spec-location">
                    <div className="spec-location-name">{dc}</div>
                    {rules.map((rule) => (
                      <div key={rule.id} className="spec-rule">
                        <span className={`spec-type spec-type-${rule.spec_type}`}>{rule.spec_type}</span>
                        <span className="spec-rule-text">{rule.rule}</span>
                        {onDeleteSpec && (
                          <button
                            className="spec-delete-btn"
                            onClick={() => onDeleteSpec(rule.id)}
                            title="Remove this spec"
                          >
                            &times;
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      )}

      {user && (
        <div className="sidebar-footer">
          <img className="user-avatar" src={user.imageUrl} alt="" />
          <span className="user-name">
            {user.firstName || user.emailAddresses?.[0]?.emailAddress || 'User'}
          </span>
          <button className="sign-out-btn" onClick={onSignOut}>Sign out</button>
        </div>
      )}
    </aside>
  )
}
