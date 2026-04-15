import { useEffect, useState } from 'react'
import { NavBar }             from './components/NavBar'
import { ActionBar }          from './components/ActionBar'
import { Dashboard }          from './components/Dashboard'
import { ChatDrawer }         from './components/ChatDrawer'
import { TradeApprovalModal } from './components/TradeApprovalModal'
import { SignalsFeed }        from './components/SignalsFeed'
import { Journal }            from './components/Journal'
import { Settings }           from './components/Settings'
import { IpoWatch }           from './components/IpoWatch'
import { api, type Balance }  from './lib/api'

type Screen = 'dashboard' | 'chat' | 'signals' | 'journal' | 'settings' | 'ipo-watch'

export default function App() {
  const [screen, setScreen]         = useState<Screen>('dashboard')
  const [chatOpen, setChatOpen]     = useState(false)
  const [chatCmd, setChatCmd]       = useState('')
  const [balance, setBalance]       = useState<Balance | null>(null)
  const [activeTicker, setActive]   = useState('')
  const [plan, setPlan]             = useState<null | Record<string, unknown>>(null)

  useEffect(() => {
    api.portfolio().then(r => setBalance(r.balance)).catch(console.error)
  }, [])

  function handleCommand(cmd: string) {
    // Extract ticker from commands like "Analyze: AMD" or "News: NVDA"
    const match = cmd.match(/:\s*([A-Z]+)/i)
    if (match) setActive(match[1].toUpperCase())
    setChatCmd(cmd)
    setChatOpen(true)
    setScreen('chat')
  }

  function handleScreenChange(s: Screen) {
    if (s === 'chat') { setChatOpen(true) }
    else { setScreen(s); setChatOpen(false) }
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <NavBar />

      <div className="flex-1 flex flex-col min-h-0 relative">
        {/* Main content area */}
        <div className="flex-1 min-h-0 overflow-hidden">
          {screen === 'dashboard' && (
            <Dashboard onCommand={handleCommand} />
          )}
          {screen === 'signals' && (
            <SignalsFeed onCommand={handleCommand} />
          )}
          {screen === 'journal' && (
            <Journal onViewPositions={() => setScreen('dashboard')} />
          )}
          {screen === 'settings' && (
            <Settings />
          )}
          {screen === 'ipo-watch' && (
            <IpoWatch onCommand={handleCommand} />
          )}
        </div>

        {/* Chat drawer — slides over all screens */}
        <ChatDrawer
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          initialCmd={chatCmd}
          balance={balance}
          activeTicker={activeTicker}
        />
      </div>

      <ActionBar onCommand={handleCommand} setScreen={handleScreenChange} />

      {/* Trade approval modal */}
      <TradeApprovalModal
        plan={plan as never}
        onClose={() => setPlan(null)}
        onExecuted={() => {
          setPlan(null)
          api.portfolio().then(r => setBalance(r.balance)).catch(console.error)
        }}
      />
    </div>
  )
}
