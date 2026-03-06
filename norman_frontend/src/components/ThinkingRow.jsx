export default function ThinkingRow() {
  return (
    <div className="message-row">
      <div className="message-avatar avatar-agent">N</div>
      <div className="thinking-content">
        Norman is thinking{' '}
        <span className="dots">
          <span></span><span></span><span></span>
        </span>
      </div>
    </div>
  )
}
