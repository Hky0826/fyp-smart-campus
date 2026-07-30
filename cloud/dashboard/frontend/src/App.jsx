import MappingNotificationPage from './features/mapping_and_notification/MappingNotificationPage.jsx'

function App() {
  return <>
    <nav className="fixed left-0 right-0 top-0 z-20 flex h-12 items-center gap-5 border-b border-slate-800 bg-slate-950/95 px-6 text-sm">
      <a href="/dashboard/" className="text-slate-400 hover:text-white">Dashboard</a>
      <a href="/dashboard/mapping-notification" className="font-semibold text-emerald-400">Mapping &amp; Notifications</a>
    </nav>
    <div className="pt-12"><MappingNotificationPage /></div>
  </>
}

export default App
