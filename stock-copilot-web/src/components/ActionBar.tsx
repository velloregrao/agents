type Screen = 'dashboard' | 'chat' | 'signals' | 'journal' | 'settings' | 'ipo-watch'

interface Props {
  onCommand: (cmd: string) => void
  setScreen: (s: Screen) => void
}

export function ActionBar({ onCommand, setScreen }: Props) {
  const actions = [
    { label: 'Analyze ▾', cmd: 'Analyze: ',   screen: 'chat'     as Screen },
    { label: 'News ▾',    cmd: 'News: ',       screen: 'chat'     as Screen },
    { label: 'Portfolio', cmd: 'Portfolio',    screen: 'dashboard'as Screen },
    { label: 'Optimize',  cmd: 'Optimize',     screen: 'chat'     as Screen },
    { label: 'Digest',    cmd: 'Digest',       screen: 'journal'  as Screen },
    { label: 'Signals',   cmd: '',             screen: 'signals'   as Screen },
    { label: 'IPO Watch', cmd: '',             screen: 'ipo-watch' as Screen },
  ]

  return (
    <div className="flex items-center gap-2 px-6 py-3 border-t border-border bg-surface shrink-0 overflow-x-auto">
      {actions.map(a => (
        <button
          key={a.label}
          onClick={() => { setScreen(a.screen); if (a.cmd) onCommand(a.cmd) }}
          className="whitespace-nowrap px-4 py-2 rounded-full border border-border text-sm text-muted
                     hover:border-accent hover:text-white transition-colors bg-transparent cursor-pointer"
        >
          {a.label}
        </button>
      ))}
    </div>
  )
}
