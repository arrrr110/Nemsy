import { useState } from 'react'
import Chat from './views/Chat'
import FileLibrary from './views/FileLibrary'
import Status from './views/Status'
import Settings from './views/Settings'

type View = 'chat' | 'files' | 'status' | 'settings'

const NAV_ITEMS: { id: View; icon: string; label: string }[] = [
  { id: 'chat',     icon: '💬', label: 'Chat'   },
  { id: 'files',    icon: '📁', label: '文件库'  },
  { id: 'status',   icon: '📊', label: '状态'    },
  { id: 'settings', icon: '⚙️', label: '设置'    },
]

export default function App() {
  const [view, setView] = useState<View>('chat')

  return (
    <div className="app">
      {/* ── Sidebar ──────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-dot" />
          Nemsy
        </div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`nav-item${view === item.id ? ' active' : ''}`}
              onClick={() => setView(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      {/* ── Main content ─────────────────────────────── */}
      <div className="main-content">
        {view === 'chat'     && <Chat />}
        {view === 'files'    && <FileLibrary />}
        {view === 'status'   && <Status />}
        {view === 'settings' && <Settings />}
      </div>
    </div>
  )
}
