import { useState, useEffect, useRef, useCallback } from 'react'
import { useClerk, useUser } from '@clerk/react'
import { apiGet, apiPost, apiPostStream } from '../lib/api'
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

  const [sidebarOpen, setSidebarOpen] = useState(true)
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

  const chatRef = useRef(null)
  const inputRef = useRef(null)

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

  useEffect(() => {
    loadConversations()
    loadLivingDocs()
  }, [loadConversations, loadLivingDocs])

  // Scroll to bottom
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [messages, isWaiting, streamingText])

  // Load a conversation from sidebar
  const loadConversation = async (id) => {
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

  // New conversation
  const newConversation = () => {
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
      />

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
            <button
              className="topbar-btn"
              onClick={refreshLivingDoc}
              disabled={isWaiting}
              title="Regenerate today's snapshot"
            >
              &#x21BB;
            </button>
          )}
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
    </>
  )
}
