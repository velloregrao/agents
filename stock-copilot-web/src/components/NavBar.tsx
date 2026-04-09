import { TrendingUp, Bell } from 'lucide-react'

export function NavBar() {
  return (
    <nav className="flex items-center justify-between px-6 py-3 border-b border-border bg-surface shrink-0">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 bg-accent rounded-lg flex items-center justify-center">
          <TrendingUp size={18} className="text-white" />
        </div>
        <span className="font-medium text-base text-white">Stock Copilot</span>
      </div>
      <div className="flex items-center gap-3">
        <button className="relative p-2 text-muted hover:text-white transition-colors">
          <Bell size={18} />
          <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full" />
        </button>
        <div className="w-8 h-8 bg-accent rounded-full flex items-center justify-center text-sm font-medium">
          JD
        </div>
      </div>
    </nav>
  )
}
