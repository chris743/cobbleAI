import { SignIn, ClerkLoaded, useAuth, useUser } from '@clerk/react'
import { useEffect } from 'react'
import { setGetToken } from './lib/api'
import ChatLayout from './components/ChatLayout'

export default function App() {
  return (
    <ClerkLoaded>
      <AppInner />
    </ClerkLoaded>
  )
}

function AppInner() {
  const { isSignedIn, getToken } = useAuth()

  useEffect(() => {
    if (isSignedIn) {
      setGetToken(getToken)
    }
  }, [isSignedIn, getToken])

  if (!isSignedIn) {
    return (
      <div className="auth-screen">
        <div className="auth-brand">Norman</div>
        <div className="auth-sub">Sign in to access CobbleAI</div>
        <SignIn />
      </div>
    )
  }

  return <ChatLayout />
}
