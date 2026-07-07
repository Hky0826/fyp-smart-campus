import {
  AlertTriangle,
  CheckCircle2,
  DoorOpen,
  Lock,
  LogOut,
  MessageSquare,
  Mic,
  RefreshCcw,
  Send,
  Shield,
  Video,
  WifiOff,
  XCircle
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { kioskClient, subscribeToKioskState } from './api/kioskClient'
import type { ChatMessage, KioskStateResponse } from './api/types'
import { CAMERA_FRAME_INTERVAL_MS } from './app/config'
import { deriveKioskMode } from './app/kioskStateMachine'

type CameraTask = 'access' | 'chat' | null

function App() {
  const [state, setState] = useState<KioskStateResponse | null>(null)
  const [nowMs, setNowMs] = useState(Date.now())
  const [cameraTask, setCameraTask] = useState<CameraTask>(null)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState('')
  const [chatError, setChatError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  const mode = deriveKioskMode(state, {
    chatVerificationActive: cameraTask === 'chat',
    nowMs
  })

  const session = state?.active_chat_session ?? null
  const accessAttempt = state?.active_access_attempt ?? null
  const cloudOnline = state?.device.cloud_chatbot === 'ok'

  const refreshState = useCallback(async () => {
    try {
      setState(await kioskClient.getState())
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => {
    refreshState()
    const unsubscribe = subscribeToKioskState(
      (nextState) => {
        setState(nextState)
        setOffline(false)
      },
      () => setOffline(true)
    )
    return unsubscribe
  }, [refreshState])

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }, [])

  useEffect(() => {
    if (!cameraTask) {
      stopCamera()
      return
    }

    let cancelled = false
    let intervalId: number | null = null

    async function startCameraLoop() {
      setCameraError(null)
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: 'user',
            width: { ideal: 1280 },
            height: { ideal: 720 }
          },
          audio: false
        })
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }

        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play()
        }

        const submitFrame = async () => {
          if (cancelled || !videoRef.current) {
            return
          }
          const frame = await captureFrame(videoRef.current)
          if (!frame) {
            return
          }
          try {
            if (cameraTask === 'access') {
              const response = await kioskClient.verifyAccessFrame(frame)
              setState((current) => mergeAccessAttempt(current, response.attempt))
              if (response.attempt.completed_at) {
                setCameraTask(null)
              }
            } else {
              const response = await kioskClient.verifyChatOwnerFrame(frame)
              setState((current) => mergeChatSession(current, response.session))
              setCameraTask(null)
              setChatError(null)
            }
          } catch (error) {
            if (cameraTask === 'chat') {
              setChatError(error instanceof Error ? error.message : 'Verification failed.')
              setCameraTask(null)
            } else {
              setCameraError(error instanceof Error ? error.message : 'Access verification failed.')
              setCameraTask(null)
            }
          }
        }

        await submitFrame()
        intervalId = window.setInterval(submitFrame, CAMERA_FRAME_INTERVAL_MS)
      } catch (error) {
        setCameraError(error instanceof Error ? error.message : 'Camera is unavailable.')
        setCameraTask(null)
      }
    }

    startCameraLoop()

    return () => {
      cancelled = true
      if (intervalId) {
        window.clearInterval(intervalId)
      }
      stopCamera()
    }
  }, [cameraTask, stopCamera])

  async function handleRequestAccess() {
    setBusy(true)
    setCameraError(null)
    try {
      await kioskClient.stopChatAudio()
      const response = await kioskClient.requestAccess()
      setState((current) => mergeAccessAttempt(current, response.attempt))
      setCameraTask('access')
    } catch (error) {
      setCameraError(error instanceof Error ? error.message : 'Could not start access verification.')
    } finally {
      setBusy(false)
    }
  }

  async function handleStartChat() {
    setChatError(null)
    setCameraTask('chat')
  }

  async function handleSendMessage(event: FormEvent) {
    event.preventDefault()
    const query = draft.trim()
    if (!query || busy || session?.locked) {
      return
    }

    setBusy(true)
    setChatError(null)
    setDraft('')
    try {
      const response = await kioskClient.sendChatMessage(query)
      setState((current) => mergeChatSession(current, response.session))
    } catch (error) {
      setDraft(query)
      setChatError(error instanceof Error ? error.message : 'Message failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleEndChat() {
    setBusy(true)
    try {
      await kioskClient.endChat()
      setState((current) => (current ? { ...current, active_chat_session: null } : current))
    } finally {
      setBusy(false)
    }
  }

  const statusText = useMemo(() => {
    if (offline) return 'Edge API offline'
    if (!state) return 'Connecting'
    if (!cloudOnline) return 'Cloud chatbot offline'
    return 'Ready'
  }, [cloudOnline, offline, state])

  return (
    <main className="kiosk-shell">
      <video ref={videoRef} className="camera-preview" playsInline muted />

      <header className="top-bar">
        <div className="brand-mark">
          <Shield size={24} aria-hidden="true" />
          <div>
            <strong>{state?.device.device_name ?? 'Door Access Kiosk'}</strong>
            <span>{state?.device.device_id ?? 'edge device'}</span>
          </div>
        </div>
        <StatusPill online={!offline} label={statusText} />
      </header>

      <section className="main-grid">
        <section className="access-panel">
          <div className="section-heading">
            <DoorOpen size={28} aria-hidden="true" />
            <div>
              <h1>Door Access</h1>
              <p>{accessSubtitle(mode, accessAttempt)}</p>
            </div>
          </div>

          <button className="primary-action" onClick={handleRequestAccess} disabled={busy || cameraTask !== null}>
            <DoorOpen size={32} aria-hidden="true" />
            <span>Request Access</span>
          </button>

          <AccessStatus mode={mode} reason={accessAttempt?.reason ?? cameraError} />
        </section>

        <section className={`chat-panel ${session?.locked ? 'is-locked' : ''}`}>
          <div className="section-heading compact">
            <MessageSquare size={24} aria-hidden="true" />
            <div>
              <h2>Campus Assistant</h2>
              <p>{chatSubtitle(session, cloudOnline)}</p>
            </div>
          </div>

          {!session && (
            <div className="chat-empty">
              <button className="secondary-action" onClick={handleStartChat} disabled={cameraTask !== null || !cloudOnline}>
                <Video size={22} aria-hidden="true" />
                <span>Verify For Chat</span>
              </button>
            </div>
          )}

          {session?.locked && (
            <div className="locked-state">
              <Lock size={36} aria-hidden="true" />
              <strong>Previous chatbot session locked.</strong>
              <span>Verify your identity to start a new session.</span>
              <button className="secondary-action" onClick={handleStartChat} disabled={cameraTask !== null || !cloudOnline}>
                <Video size={20} aria-hidden="true" />
                <span>Verify Identity</span>
              </button>
            </div>
          )}

          {session && !session.locked && (
            <>
              <ChatHistory messages={session.conversation_history} />
              <form className="chat-input-row" onSubmit={handleSendMessage}>
                <input
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  disabled={busy || mode === 'access-verifying'}
                  maxLength={2000}
                  aria-label="Chat message"
                />
                <button type="submit" className="icon-button" disabled={!draft.trim() || busy || mode === 'access-verifying'}>
                  <Send size={22} aria-hidden="true" />
                </button>
                <button type="button" className="icon-button" disabled title="Voice chat">
                  <Mic size={22} aria-hidden="true" />
                </button>
                <button type="button" className="icon-button" onClick={handleEndChat} disabled={busy} title="End chat">
                  <LogOut size={22} aria-hidden="true" />
                </button>
              </form>
            </>
          )}

          {chatError && <div className="inline-alert">{chatError}</div>}
        </section>
      </section>

      {(mode === 'access-verifying' || mode === 'chat-verifying') && (
        <div className="priority-overlay">
          <div className="scan-frame">
            <Video size={48} aria-hidden="true" />
            <h2>{mode === 'access-verifying' ? 'Verifying Access' : 'Verifying Identity'}</h2>
            <p>{mode === 'access-verifying' ? 'Chatbot interaction is paused.' : 'Face verification required.'}</p>
          </div>
        </div>
      )}

      {offline && (
        <div className="system-banner">
          <WifiOff size={20} aria-hidden="true" />
          <span>Local interface is waiting for the edge API.</span>
          <button onClick={refreshState}>
            <RefreshCcw size={18} aria-hidden="true" />
          </button>
        </div>
      )}
    </main>
  )
}

function StatusPill({ online, label }: { online: boolean; label: string }) {
  return (
    <div className={`status-pill ${online ? 'online' : 'offline'}`}>
      <span />
      {label}
    </div>
  )
}

function AccessStatus({ mode, reason }: { mode: string; reason?: string | null }) {
  if (mode === 'access-granted') {
    return (
      <div className="access-result granted">
        <CheckCircle2 size={34} aria-hidden="true" />
        <strong>Access Granted</strong>
      </div>
    )
  }
  if (mode === 'access-denied') {
    return (
      <div className="access-result denied">
        <XCircle size={34} aria-hidden="true" />
        <strong>Access Denied</strong>
        {reason && <span>{reason}</span>}
      </div>
    )
  }
  if (reason) {
    return (
      <div className="access-result warning">
        <AlertTriangle size={28} aria-hidden="true" />
        <span>{reason}</span>
      </div>
    )
  }
  return <div className="access-idle">Awaiting access request</div>
}

function ChatHistory({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return <div className="chat-history empty">No active conversation.</div>
  }
  return (
    <div className="chat-history">
      {messages.map((message, index) => (
        <article key={`${message.created_at}-${index}`} className={`message ${message.role}`}>
          <p>{message.content}</p>
          {message.citations.length > 0 && <span>{message.citations.length} source{message.citations.length === 1 ? '' : 's'}</span>}
        </article>
      ))}
    </div>
  )
}

function accessSubtitle(mode: string, attempt: KioskStateResponse['active_access_attempt']) {
  if (mode === 'access-verifying') return 'Face verification in progress'
  if (attempt?.access_decision === 'GRANTED') return 'Entry decision confirmed'
  if (attempt?.access_decision === 'DENIED') return 'Entry request denied'
  return 'Primary access control surface'
}

function chatSubtitle(session: KioskStateResponse['active_chat_session'], cloudOnline: boolean) {
  if (!cloudOnline) return 'Cloud retrieval unavailable'
  if (!session) return 'Identity required'
  if (session.locked) return 'Owner absent'
  return session.full_name || session.username || 'Authenticated'
}

function mergeAccessAttempt(current: KioskStateResponse | null, attempt: NonNullable<KioskStateResponse['active_access_attempt']>) {
  if (!current) return current
  return { ...current, active_access_attempt: attempt }
}

function mergeChatSession(current: KioskStateResponse | null, session: NonNullable<KioskStateResponse['active_chat_session']>) {
  if (!current) return current
  return { ...current, active_chat_session: session }
}

async function captureFrame(video: HTMLVideoElement): Promise<Blob | null> {
  if (!video.videoWidth || !video.videoHeight) {
    return null
  }
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const context = canvas.getContext('2d')
  if (!context) {
    return null
  }
  context.drawImage(video, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.82))
}

export default App
