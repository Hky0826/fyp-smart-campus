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

function App() {
  const [state, setState] = useState<KioskStateResponse | null>(null)
  const [nowMs, setNowMs] = useState(Date.now())
  const [chatVerificationActive, setChatVerificationActive] = useState(false)
  const [cameraReady, setCameraReady] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState('')
  const [chatError, setChatError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const frameInFlightRef = useRef(false)

  const mode = deriveKioskMode(state, {
    chatVerificationActive,
    nowMs
  })

  const session = state?.active_chat_session ?? null
  const accessAttempt = state?.active_access_attempt ?? null
  const cloudOnline = state?.device.cloud_chatbot === 'ok'
  const ownerMissing = session?.presence_state === 'OWNER_TEMPORARILY_MISSING'
  const absentSecondsRemaining = useMemo(() => {
    const terminateSeconds = state?.timings.owner_absent_terminate_seconds ?? 10
    if (!session?.locked || !session.owner_absent_since) {
      return terminateSeconds
    }
    const absentSinceMs = Date.parse(session.owner_absent_since)
    if (!Number.isFinite(absentSinceMs)) {
      return terminateSeconds
    }
    return Math.max(0, Math.ceil(terminateSeconds - (nowMs - absentSinceMs) / 1000))
  }, [nowMs, session?.locked, session?.owner_absent_since, state?.timings.owner_absent_terminate_seconds])

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

  useEffect(() => {
    let cancelled = false

    async function startCamera() {
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
        setCameraReady(true)
        setCameraError(null)
      } catch (error) {
        setCameraReady(false)
        setCameraError(error instanceof Error ? error.message : 'Camera is unavailable.')
      }
    }

    startCamera()

    return () => {
      cancelled = true
      streamRef.current?.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!cameraReady || offline) {
      return
    }

    const intervalId = window.setInterval(async () => {
      if (frameInFlightRef.current || !videoRef.current) {
        return
      }

      const frame = await captureFrame(videoRef.current)
      if (!frame) {
        return
      }

      frameInFlightRef.current = true
      try {
        if (chatVerificationActive) {
          const response = await kioskClient.verifyChatOwnerFrame(frame)
          setState((current) => mergeChatSession(current, response.session))
          setChatVerificationActive(false)
          setChatError(null)
          return
        }

        if (session) {
          const presence = await kioskClient.verifyChatPresenceFrame(frame)
          if (presence.ended) {
            setState((current) => (current ? { ...current, active_chat_session: null } : current))
            setChatError(null)
            return
          }
          const presenceSession = presence.session
          if (presenceSession) {
            setState((current) => mergeChatSession(current, presenceSession))
          }

          if (!presence.owner_present) {
            const accessResponse = await kioskClient.verifyAccessFrame(frame)
            setState((current) => mergeAccessAttempt(current, accessResponse.attempt))
          }
          return
        }

        const accessResponse = await kioskClient.verifyAccessFrame(frame)
        setState((current) => mergeAccessAttempt(current, accessResponse.attempt))
      } catch (error) {
        if (chatVerificationActive) {
          setChatError(error instanceof Error ? error.message : 'Face verification failed.')
          setChatVerificationActive(false)
        } else {
          setCameraError(error instanceof Error ? error.message : 'Frame processing failed.')
        }
      } finally {
        frameInFlightRef.current = false
      }
    }, CAMERA_FRAME_INTERVAL_MS)

    return () => window.clearInterval(intervalId)
  }, [cameraReady, chatVerificationActive, offline, session])

  async function handleStartChat() {
    setChatError(null)
    setCameraError(null)
    try {
      await kioskClient.stopChatAudio()
    } catch {
      // Browser text chat can still start even if there is no audio output to stop.
    }
    setChatVerificationActive(true)
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
    if (!cameraReady) return 'Camera unavailable'
    if (!cloudOnline) return 'Cloud chatbot offline'
    return session ? 'Chatbot mode' : 'Door monitoring'
  }, [cameraReady, cloudOnline, offline, session, state])

  return (
    <main className="kiosk-shell">
      <header className="top-bar">
        <div className="brand-mark">
          <Shield size={24} aria-hidden="true" />
          <div>
            <strong>{state?.device.device_name ?? 'Door Access Kiosk'}</strong>
            <span>{state?.device.device_id ?? 'edge device'}</span>
          </div>
        </div>
        <StatusPill online={!offline && cameraReady} label={statusText} />
      </header>

      <section className="main-grid">
        <section className="access-panel">
          <div className="section-heading">
            <DoorOpen size={28} aria-hidden="true" />
            <div>
              <h1>Door Access</h1>
              <p>{accessSubtitle(mode, accessAttempt, Boolean(session))}</p>
            </div>
          </div>

          <div className="camera-stage">
            <video ref={videoRef} className="camera-feed" playsInline muted />
            <div className="camera-badge">
              <Video size={18} aria-hidden="true" />
              <span>{session && !session.locked ? 'Chatbot owner tracking' : 'Continuous access scan'}</span>
            </div>
          </div>

          <AccessStatus mode={mode} attempt={accessAttempt} reason={cameraError} />
        </section>

        <section className={`chat-panel ${session?.locked ? 'is-locked' : ''}`}>
          <div className="section-heading compact">
            <MessageSquare size={24} aria-hidden="true" />
            <div>
              <h2>Campus Assistant</h2>
              <p>{chatSubtitle(session, cloudOnline, chatVerificationActive)}</p>
            </div>
          </div>

          {!session && (
            <div className="chat-empty">
              <button className="secondary-action" onClick={handleStartChat} disabled={chatVerificationActive || !cloudOnline || !cameraReady}>
                <MessageSquare size={22} aria-hidden="true" />
                <span>Start Chatbot</span>
              </button>
            </div>
          )}

          {session?.locked && (
            <div className="locked-state">
              <Lock size={36} aria-hidden="true" />
              <strong>{ownerMissing ? 'Owner temporarily away.' : 'Previous chatbot session locked.'}</strong>
              <span>Session will close after {absentSecondsRemaining} seconds unless the verified user returns.</span>
            </div>
          )}

          {session && !session.locked && (
            <>
              <ChatHistory messages={session.conversation_history} />
              <form className="chat-input-row" onSubmit={handleSendMessage}>
                <input
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  disabled={busy}
                  maxLength={2000}
                  aria-label="Chat message"
                />
                <button type="submit" className="icon-button" disabled={!draft.trim() || busy}>
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

          {chatVerificationActive && (
            <div className="inline-info">
              <Video size={20} aria-hidden="true" />
              <span>Look at the camera to verify chatbot identity.</span>
            </div>
          )}

          {chatError && <div className="inline-alert">{chatError}</div>}
        </section>
      </section>

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

function AccessStatus({
  mode,
  attempt,
  reason
}: {
  mode: string
  attempt?: KioskStateResponse['active_access_attempt']
  reason?: string | null
}) {
  if (mode === 'access-granted') {
    return (
      <div className="access-result granted">
        <CheckCircle2 size={34} aria-hidden="true" />
        <strong>Access Granted</strong>
        <span>Door unlock request accepted by edge access control.</span>
      </div>
    )
  }
  if (mode === 'access-denied') {
    return (
      <div className="access-result denied">
        <XCircle size={34} aria-hidden="true" />
        <strong>Access Denied</strong>
        {attempt?.reason && <span>{attempt.reason}</span>}
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
  return <div className="access-idle">Monitoring the entrance continuously</div>
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

function accessSubtitle(mode: string, attempt: KioskStateResponse['active_access_attempt'], hasSession: boolean) {
  if (hasSession && mode === 'chat-active') return 'Paused while verified user uses chatbot'
  if (mode === 'chat-locked') return 'Owner away; door access remains active'
  if (mode === 'access-granted') return 'Entry decision confirmed'
  if (mode === 'access-denied' && attempt?.face_count) return 'Entry request denied'
  return 'Continuous face recognition is active'
}

function chatSubtitle(session: KioskStateResponse['active_chat_session'], cloudOnline: boolean, verifying: boolean) {
  if (!cloudOnline) return 'Cloud retrieval unavailable'
  if (verifying) return 'Verifying identity'
  if (!session) return 'Press to start'
  if (session.locked) return 'Waiting for owner return'
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
