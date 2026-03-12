import { useState, useEffect, useRef, useCallback } from 'react'
import { useClerk, useUser } from '@clerk/react'
import { apiGet, apiPost, apiPostStream, apiPut, apiDelete } from '../lib/api'
import Sidebar from './Sidebar'
import MessageRow from './MessageRow'
import ThinkingRow from './ThinkingRow'

const SUGGESTIONS = [
  { label: 'Bin inventory by commodity', q: "What's our current bin inventory by commodity?" },
  { label: "Today's production", q: "Show me today's packing production summary" },
  { label: 'Open sales orders', q: 'What are the open sales orders this week?' },
  { label: "Yesterday's receivings", q: 'How many bins did we receive yesterday?' },
]

export default function ChatLayout() {
  const { signOut } = useClerk()
  const { user } = useUser()

  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 768)
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('theme')
    return saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)
  })
  const [conversations, setConversations] = useState([])
  const [conversationId, setConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [streamingText, setStreamingText] = useState('')
  const [toolName, setToolName] = useState(null)
  const [isWaiting, setIsWaiting] = useState(false)
  const [input, setInput] = useState('')

  // Living documents state
  const [livingDocs, setLivingDocs] = useState([])
  const [livingDocView, setLivingDocView] = useState(null)
  // livingDocView shape: { id, name, description, snapshot: { date, content, generated_at, is_today } | null }
  const [editingDoc, setEditingDoc] = useState(null)
  // editingDoc shape: { id, name, description, prompt } | null

  // Customer specs state
  const [customerSpecs, setCustomerSpecs] = useState([])

  // Settings modal state
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [o365Status, setO365Status] = useState({ configured: false, connected: false })

  const chatRef = useRef(null)
  const inputRef = useRef(null)

  const isMobile = () => window.innerWidth <= 768
  const closeSidebarOnMobile = () => { if (isMobile()) setSidebarOpen(false) }

  // Theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light')
    localStorage.setItem('theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  // Load conversation list
  const loadConversations = useCallback(async () => {
    try {
      const data = await apiGet('/conversations')
      setConversations(data)
    } catch (e) {
      console.error('Failed to load conversations:', e)
    }
  }, [])

  // Load living documents list
  const loadLivingDocs = useCallback(async () => {
    try {
      const data = await apiGet('/living-docs')
      setLivingDocs(data)
    } catch (e) {
      console.error('Failed to load living docs:', e)
    }
  }, [])

  // Load customer specs
  const loadCustomerSpecs = useCallback(async () => {
    try {
      const data = await apiGet('/customer-specs')
      setCustomerSpecs(data)
    } catch (e) {
      console.error('Failed to load customer specs:', e)
    }
  }, [])

  // Load O365 connection status
  const loadO365Status = useCallback(async () => {
    try {
      const data = await apiGet('/o365/status')
      setO365Status(data)
    } catch (e) {
      console.error('Failed to load O365 status:', e)
    }
  }, [])

  // O365 connect via popup
  const connectO365 = async () => {
    try {
      const data = await apiGet('/o365/auth-url')
      const popup = window.open(data.url, 'o365-auth', 'width=600,height=700,scrollbars=yes')
      if (!popup) {
        alert('Please allow popups to connect Microsoft 365.')
      }
    } catch (e) {
      console.error('Failed to start O365 auth:', e)
    }
  }

  const disconnectO365 = async () => {
    if (!window.confirm('Disconnect Microsoft 365? You can reconnect anytime.')) return
    try {
      await apiPost('/o365/disconnect', {})
      setO365Status((prev) => ({ ...prev, connected: false }))
    } catch (e) {
      console.error('Failed to disconnect O365:', e)
    }
  }

  // Listen for popup callback message
  useEffect(() => {
    const handler = (event) => {
      if (event.data?.type === 'o365-auth') {
        if (event.data.status === 'connected') {
          setO365Status((prev) => ({ ...prev, connected: true }))
        }
        loadO365Status()
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [loadO365Status])

  // Delete a customer spec by ID
  const deleteCustomerSpec = async (specId) => {
    if (!window.confirm('Remove this customer spec?')) return
    try {
      await apiDelete(`/customer-specs/${specId}`)
      loadCustomerSpecs()
    } catch (e) {
      console.error('Failed to delete customer spec:', e)
    }
  }

  useEffect(() => {
    loadConversations()
    loadLivingDocs()
    loadCustomerSpecs()
    loadO365Status()
  }, [loadConversations, loadLivingDocs, loadCustomerSpecs, loadO365Status])

  // Scroll to bottom
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [messages, isWaiting, streamingText])

  // Load a conversation from sidebar
  const loadConversation = async (id) => {
    closeSidebarOnMobile()
    setLivingDocView(null)
    try {
      const data = await apiGet(`/conversations/${id}`)
      setConversationId(data.id)
      setMessages(data.messages.map((m) => ({
        role: m.role === 'assistant' ? 'agent' : m.role,
        content: m.content,
      })))
      loadConversations()
    } catch (e) {
      console.error('Failed to load conversation:', e)
    }
  }

  // Open a living document
  const openLivingDoc = async (doc) => {
    closeSidebarOnMobile()
    setLivingDocView({ id: doc.id, name: doc.name, description: doc.description, snapshot: null })
    setConversationId(null)
    setMessages([])
    setStreamingText('')
    setToolName(null)

    try {
      const data = await apiGet(`/living-docs/${doc.id}`)
      setLivingDocView({
        id: data.id,
        name: data.name,
        description: data.description,
        snapshot: data.snapshot,
      })
      if (data.snapshot) {
        setMessages([{ role: 'agent', content: data.snapshot.content }])
      }
    } catch (e) {
      console.error('Failed to load living doc:', e)
    }
  }

  // Stream-refresh a living document (regenerate today's snapshot)
  const refreshLivingDoc = async () => {
    if (!livingDocView || isWaiting) return

    setMessages([])
    setIsWaiting(true)
    setStreamingText('')
    setToolName(null)

    let fullText = ''

    try {
      await apiPostStream(`/living-docs/${livingDocView.id}/refresh`, {}, (event) => {
        switch (event.type) {
          case 'token':
            fullText += event.text
            setStreamingText(fullText)
            setToolName(null)
            break
          case 'tool':
            setToolName(event.name)
            break
          case 'error':
            setMessages([{ role: 'error', content: event.message }])
            break
          case 'done':
            break
        }
      })

      if (fullText) {
        const today = new Date().toISOString().split('T')[0]
        setMessages([{ role: 'agent', content: fullText }])
        setLivingDocView((prev) => ({
          ...prev,
          snapshot: {
            content: fullText,
            date: today,
            generated_at: new Date().toISOString(),
            is_today: true,
          },
        }))
      }
    } catch (err) {
      setMessages([{ role: 'error', content: err.message }])
    }

    setStreamingText('')
    setToolName(null)
    setIsWaiting(false)
  }

  // Open edit modal for current living doc
  const startEditLivingDoc = async () => {
    if (!livingDocView) return
    try {
      const data = await apiGet(`/living-docs/${livingDocView.id}`)
      setEditingDoc({ id: data.id, name: data.name, description: data.description || '', prompt: data.prompt })
    } catch (e) {
      console.error('Failed to load doc for editing:', e)
    }
  }

  // Save living doc edits
  const saveEditLivingDoc = async () => {
    if (!editingDoc) return
    try {
      const updated = await apiPut(`/living-docs/${editingDoc.id}`, {
        name: editingDoc.name,
        description: editingDoc.description,
        prompt: editingDoc.prompt,
      })
      setLivingDocView((prev) => prev ? { ...prev, name: updated.name, description: updated.description } : prev)
      setEditingDoc(null)
      loadLivingDocs()
    } catch (e) {
      console.error('Failed to update living doc:', e)
    }
  }

  // Delete living doc
  const deleteLivingDoc = async () => {
    if (!livingDocView) return
    if (!window.confirm(`Delete "${livingDocView.name}"? This cannot be undone.`)) return
    try {
      await apiDelete(`/living-docs/${livingDocView.id}`)
      setLivingDocView(null)
      setMessages([])
      loadLivingDocs()
    } catch (e) {
      console.error('Failed to delete living doc:', e)
    }
  }

  // New conversation
  const newConversation = () => {
    closeSidebarOnMobile()
    setLivingDocView(null)
    setConversationId(null)
    setMessages([])
    loadConversations()
    inputRef.current?.focus()
  }

  // Send message with streaming
  const sendMessage = async (text) => {
    text = text || input.trim()
    if (!text || isWaiting) return

    // Exit doc view when user sends a message
    setLivingDocView(null)

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setIsWaiting(true)
    setStreamingText('')
    setToolName(null)

    let fullText = ''

    try {
      await apiPostStream('/chat/stream', {
        message: text,
        conversation_id: conversationId,
      }, (event) => {
        switch (event.type) {
          case 'meta':
            setConversationId(event.conversation_id)
            break
          case 'token':
            fullText += event.text
            setStreamingText(fullText)
            setToolName(null)
            break
          case 'tool':
            setToolName(event.name)
            break
          case 'error':
            setMessages((prev) => [...prev, { role: 'error', content: event.message }])
            break
          case 'done':
            break
        }
      })

      // Streaming finished — commit the full message
      if (fullText) {
        setMessages((prev) => [...prev, { role: 'agent', content: fullText }])
      }
      loadConversations()
      // Reload living docs in case the agent created one via /living-doc-add
      loadLivingDocs()
      // Reload customer specs in case the agent saved new ones
      loadCustomerSpecs()
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'error', content: err.message }])
    }

    setStreamingText('')
    setToolName(null)
    setIsWaiting(false)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handleTextareaInput = (e) => {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 150) + 'px'
  }

  const showWelcome = messages.length === 0 && !isWaiting && !livingDocView

  // Snapshot freshness label for doc view
  const snapshotLabel = livingDocView?.snapshot
    ? livingDocView.snapshot.is_today
      ? `Today · ${new Date(livingDocView.snapshot.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
      : `Last generated ${livingDocView.snapshot.date}`
    : null

  return (
    <>
      <Sidebar
        open={sidebarOpen}
        conversations={conversations}
        activeId={livingDocView ? null : conversationId}
        onSelect={loadConversation}
        onNew={newConversation}
        user={user}
        onSignOut={() => signOut()}
        livingDocs={livingDocs}
        activeLivingDocId={livingDocView?.id ?? null}
        onSelectLivingDoc={openLivingDoc}
        customerSpecs={customerSpecs}
        onDeleteSpec={deleteCustomerSpec}
      />

      {/* Mobile backdrop */}
      {sidebarOpen && (
        <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />
      )}

      <div className="main">
        {/* Topbar */}
        <div className="topbar">
          <button className="topbar-btn" onClick={() => setSidebarOpen(!sidebarOpen)}>
            <svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
          <span className="topbar-title">
            {livingDocView
              ? `\uD83D\uDCCB ${livingDocView.name}`
              : conversationId
                ? conversations.find((c) => c.id === conversationId)?.title || 'Chat'
                : 'New Conversation'}
          </span>
          {livingDocView && snapshotLabel && (
            <span className="living-doc-date">{snapshotLabel}</span>
          )}
          <div className="topbar-spacer" />
          {livingDocView && (
            <>
              <button
                className="topbar-btn"
                onClick={refreshLivingDoc}
                disabled={isWaiting}
                title="Regenerate today's snapshot"
              >
                &#x21BB;
              </button>
              <button
                className="topbar-btn"
                onClick={startEditLivingDoc}
                disabled={isWaiting}
                title="Edit document settings"
              >
                &#x270E;
              </button>
              <button
                className="topbar-btn topbar-btn-danger"
                onClick={deleteLivingDoc}
                disabled={isWaiting}
                title="Delete document"
              >
                &#x2715;
              </button>
            </>
          )}
          <button className="topbar-btn" onClick={() => setSettingsOpen(true)} title="Settings">
            <svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 100-6 3 3 0 000 6z"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
          </button>
          <button className="topbar-btn" onClick={() => setDarkMode(!darkMode)} title="Toggle dark mode">
            {darkMode ? '\u2600' : '\u263E'}
          </button>
        </div>

        {/* Chat area */}
        <div className="chat-container" ref={chatRef}>
          {showWelcome ? (
            <div className="welcome">
              <div className="welcome-avatar">N</div>
              <h2>Hello, I'm Norman</h2>
              <p>Your data warehouse assistant for citrus operations. I can help with inventory, sales, production, harvest planning, and more.</p>
              <div className="welcome-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s.q} className="suggestion-chip" onClick={() => sendMessage(s.q)}>
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          ) : livingDocView && messages.length === 0 && !isWaiting ? (
            <div className="welcome">
              <div className="welcome-avatar">&#x1F4CB;</div>
              <h2>{livingDocView.name}</h2>
              {livingDocView.description && <p>{livingDocView.description}</p>}
              <p style={{ opacity: 0.6 }}>
                {livingDocView.snapshot
                  ? "No snapshot available for today yet."
                  : "No snapshot has been generated yet."}
                {" "}Click &#x21BB; above to generate now.
              </p>
            </div>
          ) : (
            <>
              {messages.map((msg, i) => (
                <MessageRow key={i} role={msg.role} content={msg.content} />
              ))}
              {isWaiting && streamingText && (
                <MessageRow role="agent" content={streamingText} streaming />
              )}
              {isWaiting && !streamingText && (
                <ThinkingRow toolName={toolName} />
              )}
            </>
          )}
        </div>

        {/* Input — hidden in doc view, shown in chat mode */}
        {livingDocView ? (
          <div className="input-area">
            <div className="living-doc-footer">
              This is a shared living document — all users see the same content.
              <button className="living-doc-back-btn" onClick={newConversation}>
                Return to chat
              </button>
            </div>
          </div>
        ) : (
          <div className="input-area">
            <div className="input-wrapper">
              <textarea
                ref={inputRef}
                value={input}
                onChange={handleTextareaInput}
                onKeyDown={handleKeyDown}
                placeholder="Ask Norman anything about your operations... (try /living-doc-add)"
                rows={1}
              />
              <button className="send-btn" onClick={() => sendMessage()} disabled={isWaiting || !input.trim()}>
                <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
              </button>
            </div>
            <div className="input-hint">Press Enter to send, Shift+Enter for a new line</div>
          </div>
        )}
      </div>

      {/* Edit living doc modal */}
      {editingDoc && (
        <div className="modal-overlay" onClick={() => setEditingDoc(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Edit Living Document</h3>
            <label className="modal-label">
              Name
              <input
                className="modal-input"
                value={editingDoc.name}
                onChange={(e) => setEditingDoc({ ...editingDoc, name: e.target.value })}
              />
            </label>
            <label className="modal-label">
              Description
              <input
                className="modal-input"
                value={editingDoc.description}
                onChange={(e) => setEditingDoc({ ...editingDoc, description: e.target.value })}
              />
            </label>
            <label className="modal-label">
              Prompt
              <textarea
                className="modal-textarea"
                value={editingDoc.prompt}
                onChange={(e) => setEditingDoc({ ...editingDoc, prompt: e.target.value })}
                rows={6}
              />
            </label>
            <div className="modal-actions">
              <button className="modal-btn modal-btn-secondary" onClick={() => setEditingDoc(null)}>Cancel</button>
              <button className="modal-btn modal-btn-primary" onClick={saveEditLivingDoc}>Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Settings modal */}
      {settingsOpen && (
        <div className="modal-overlay" onClick={() => setSettingsOpen(false)}>
          <div className="modal settings-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Settings</h3>

            <div className="settings-section">
              <div className="settings-section-title">Connections</div>

              <div className="connection-card">
                <div className="connection-header">
                  <svg className="connection-icon" viewBox="0 0 24 24" fill="none">
                    <rect x="1" y="1" width="10" height="10" fill="#F25022"/>
                    <rect x="13" y="1" width="10" height="10" fill="#7FBA00"/>
                    <rect x="1" y="13" width="10" height="10" fill="#00A4EF"/>
                    <rect x="13" y="13" width="10" height="10" fill="#FFB900"/>
                  </svg>
                  <div className="connection-info">
                    <div className="connection-name">Microsoft 365</div>
                    <div className="connection-desc">
                      Email, calendar, OneDrive, and SharePoint access
                    </div>
                  </div>
                  <div className={`connection-status ${o365Status.connected ? 'connected' : ''}`}>
                    {o365Status.connected ? 'Connected' : 'Not connected'}
                  </div>
                </div>

                {!o365Status.configured ? (
                  <div className="connection-note">
                    Microsoft 365 integration is not configured on the server. Contact your administrator to set up O365_CLIENT_ID and O365_CLIENT_SECRET.
                  </div>
                ) : o365Status.connected ? (
                  <div className="connection-actions">
                    <div className="connection-note connected-note">
                      Norman can now read your emails, calendar, OneDrive, and SharePoint. Just ask!
                    </div>
                    <button className="modal-btn modal-btn-danger" onClick={disconnectO365}>
                      Disconnect
                    </button>
                  </div>
                ) : (
                  <div className="connection-actions">
                    <button className="modal-btn modal-btn-primary" onClick={connectO365}>
                      Connect Microsoft 365
                    </button>
                  </div>
                )}

                {o365Status.connected && (
                  <div className="connection-capabilities">
                    <span className="capability-tag">Email</span>
                    <span className="capability-tag">Calendar</span>
                    <span className="capability-tag">OneDrive</span>
                    <span className="capability-tag">SharePoint</span>
                  </div>
                )}
              </div>
            </div>

            <div className="modal-actions">
              <button className="modal-btn modal-btn-secondary" onClick={() => setSettingsOpen(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
