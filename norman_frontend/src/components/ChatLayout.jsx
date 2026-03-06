import { useState, useEffect, useRef, useCallback } from 'react'
import { useClerk, useUser } from '@clerk/react'
import { apiGet, apiPost } from '../lib/api'
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
  const [isWaiting, setIsWaiting] = useState(false)
  const [input, setInput] = useState('')

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

  useEffect(() => { loadConversations() }, [loadConversations])

  // Scroll to bottom
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [messages, isWaiting])

  // Load a conversation from sidebar
  const loadConversation = async (id) => {
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

  // New conversation
  const newConversation = () => {
    setConversationId(null)
    setMessages([])
    loadConversations()
    inputRef.current?.focus()
  }

  // Send message
  const sendMessage = async (text) => {
    text = text || input.trim()
    if (!text || isWaiting) return

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setIsWaiting(true)

    try {
      const data = await apiPost('/chat', {
        message: text,
        conversation_id: conversationId,
      })
      setConversationId(data.conversation_id)
      setMessages((prev) => [...prev, { role: 'agent', content: data.response }])
      loadConversations()
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'error', content: err.message }])
    }

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

  const showWelcome = messages.length === 0

  return (
    <>
      <Sidebar
        open={sidebarOpen}
        conversations={conversations}
        activeId={conversationId}
        onSelect={loadConversation}
        onNew={newConversation}
        user={user}
        onSignOut={() => signOut()}
      />

      <div className="main">
        {/* Topbar */}
        <div className="topbar">
          <button className="topbar-btn" onClick={() => setSidebarOpen(!sidebarOpen)}>
            <svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
          <span className="topbar-title">
            {conversationId ? conversations.find((c) => c.id === conversationId)?.title || 'Chat' : 'New Conversation'}
          </span>
          <div className="topbar-spacer" />
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
          ) : (
            <>
              {messages.map((msg, i) => (
                <MessageRow key={i} role={msg.role} content={msg.content} />
              ))}
              {isWaiting && <ThinkingRow />}
            </>
          )}
        </div>

        {/* Input */}
        <div className="input-area">
          <div className="input-wrapper">
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleTextareaInput}
              onKeyDown={handleKeyDown}
              placeholder="Ask Norman anything about your operations..."
              rows={1}
            />
            <button className="send-btn" onClick={() => sendMessage()} disabled={isWaiting || !input.trim()}>
              <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            </button>
          </div>
          <div className="input-hint">Press Enter to send, Shift+Enter for a new line</div>
        </div>
      </div>
    </>
  )
}
