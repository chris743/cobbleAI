export default function Sidebar({ open, conversations, activeId, onSelect, onNew, user, onSignOut }) {
  return (
    <aside className={`sidebar ${open ? '' : 'collapsed'}`}>
      <div className="sidebar-header">
        <div className="sidebar-logo">N</div>
        <div className="sidebar-brand">
          Norman
          <small>Powered by Cobblestone Fruit Company</small>
        </div>
      </div>

      <button className="new-chat-btn" onClick={onNew}>
        <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        New Conversation
      </button>

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
