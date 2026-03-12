import { SignIn, ClerkLoaded, ClerkLoading, useAuth } from '@clerk/react'
import { useEffect } from 'react'
import { setGetToken } from './lib/api'
import ChatLayout from './components/ChatLayout'

export default function App() {
  return (
    <>
      <ClerkLoading>
        <div className="auth-screen">
          <div className="auth-brand">Norman</div>
          <div className="auth-sub">Loading...</div>
        </div>
      </ClerkLoading>
      <ClerkLoaded>
        <AppInner />
      </ClerkLoaded>
    </>
  )
}

function AppInner() {
  const { isSignedIn, isLoaded, getToken } = useAuth()

  useEffect(() => {
    if (isSignedIn) {
      setGetToken(getToken)
    }
  }, [isSignedIn, getToken])

  if (!isLoaded) {
    return (
      <div className="auth-screen">
        <div className="auth-brand">Norman</div>
        <div className="auth-sub">Loading...</div>
      </div>
    )
  }

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
