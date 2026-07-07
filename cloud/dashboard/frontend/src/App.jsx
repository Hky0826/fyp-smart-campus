import React from 'react'

function App() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4 relative overflow-hidden text-slate-100">
      {/* Background gradients */}
      <div className="absolute top-[-20%] left-[-20%] w-[60%] h-[60%] bg-emerald-900/10 rounded-full blur-[120px]"></div>
      
      <div className="w-full max-w-lg bg-slate-900/70 border border-slate-800 rounded-3xl p-8 md:p-10 shadow-2xl backdrop-blur-xl relative z-10 text-center">
        <h1 className="text-2xl font-bold tracking-tight text-slate-100 mb-4">
          Smart Campus Dashboard Skeleton
        </h1>
        <p className="text-slate-400 text-sm mb-6 leading-relaxed">
          This React + Vite development environment skeleton is configured under <code className="text-emerald-400 font-mono text-xs">/dashboard/frontend</code>.
        </p>
        
        <div className="bg-slate-950 border border-slate-800/80 rounded-2xl p-4 text-left mb-6 space-y-3">
          <p className="text-xs text-slate-500 font-bold uppercase tracking-wider">How to start this modular frontend:</p>
          <ol className="list-decimal list-inside text-xs text-slate-300 space-y-2 font-mono">
            <li>Open terminal in <code className="text-emerald-400">dashboard/frontend</code></li>
            <li>Run <code className="text-emerald-400">npm install</code> to fetch dependencies</li>
            <li>Run <code className="text-emerald-400">npm run dev</code> to boot Vite server</li>
          </ol>
        </div>

        <div className="border-t border-slate-800/50 pt-5">
          <p className="text-xs text-slate-400">
            For an out-of-the-box working portal, run the FastAPI server and navigate to:
          </p>
          <p className="text-sm font-bold text-emerald-400 mt-2 font-mono">
            http://127.0.0.1:8000/dashboard
          </p>
        </div>
      </div>
    </div>
  )
}

export default App
