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
  X,
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
  const [chatExpanded, setChatExpanded] = useState(false)
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
  const syncConnected = state?.device.cloud_sync === 'connected'
  const cloudChatbotOnline = state?.device.cloud_chatbot === 'ok'
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
      const getUserMedia = navigator.mediaDevices?.getUserMedia?.bind(navigator.mediaDevices)
      if (!getUserMedia) {
        setCameraReady(false)
        setCameraError(
          'Camera API is unavailable in this browser context. Open the kiosk locally in Chromium at http://127.0.0.1:8080/ui/ and allow camera access.'
        )
        return
      }

      try {
        const stream = await getUserMedia({
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
            setChatExpanded(false)
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

  async function handleOpenChat() {
    setChatExpanded(true)
    if (!session && !chatVerificationActive) {
      await handleStartChat()
    }
  }

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
      setChatExpanded(false)
    } finally {
      setBusy(false)
    }
  }

  const cameraStatusText = useMemo(() => {
    if (offline) return 'Edge API offline'
    if (!state) return 'Connecting'
    if (!cameraReady) return 'Camera unavailable'
    if (session && !session.locked) return 'Chatbot owner tracking'
    if (session?.locked) return 'Door access active'
    return 'Continuous access recognition'
  }, [cameraReady, offline, session, state])

  return (
    <main className="kiosk-shell">
      <section className="camera-fullscreen">
        <video ref={videoRef} className="camera-feed" playsInline muted />
        <div className="camera-shade" />
      </section>

      <header className="top-bar">
        <div className="brand-mark">
          <Shield size={24} aria-hidden="true" />
          <div>
            <strong>{state?.device.device_name ?? 'Door Access Kiosk'}</strong>
            <span>{state?.device.device_id ?? 'edge device'}</span>
          </div>
        </div>
        <div className="status-row">
          <StatusPill online={!offline && cameraReady} label={cameraStatusText} />
          <StatusPill online={Boolean(syncConnected)} label={`Sync ${state?.device.cloud_sync ?? 'unknown'}`} />
        </div>
      </header>

      <section className="access-hud">
        <div className="section-heading">
          <DoorOpen size={28} aria-hidden="true" />
          <div>
            <h1>Door Access</h1>
            <p>{accessSubtitle(mode, accessAttempt, Boolean(session && !session.locked))}</p>
          </div>
        </div>
        <AccessStatus mode={mode} attempt={accessAttempt} reason={cameraError} />
      </section>

      <button className="chat-launcher" onClick={handleOpenChat} disabled={!cameraReady || offline}>
        <MessageSquare size={28} aria-hidden="true" />
        <span>{session ? 'Chatbot' : 'Start Chat'}</span>
      </button>

      {chatExpanded && (
        <section className="chat-overlay">
          <div className="chat-window">
            <div className="chat-header">
              <div className="section-heading compact">
                <MessageSquare size={24} aria-hidden="true" />
                <div>
                  <h2>Campus Assistant</h2>
                  <p>{chatSubtitle(session, cloudChatbotOnline, chatVerificationActive)}</p>
                </div>
              </div>
              <button className="icon-button dark" onClick={() => setChatExpanded(false)} title="Collapse chat">
                <X size={22} aria-hidden="true" />
              </button>
            </div>

            {!session && !chatVerificationActive && (
              <div className="chat-empty">
                <button className="secondary-action" onClick={handleStartChat} disabled={!cameraReady}>
                  <Video size={22} aria-hidden="true" />
                  <span>Verify Identity</span>
                </button>
              </div>
            )}

            {chatVerificationActive && (
              <div className="chat-empty">
                <Video size={40} aria-hidden="true" />
                <strong>Look at the camera</strong>
                <span>Verifying chatbot identity.</span>
              </div>
            )}

            {session?.locked && (
              <div className="locked-state">
                <Lock size={42} aria-hidden="true" />
                <strong>{ownerMissing ? 'Owner temporarily away.' : 'Previous chatbot session locked.'}</strong>
                <span>Session closes in {absentSecondsRemaining} seconds unless the verified user returns.</span>
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

            {chatError && <div className="inline-alert">{chatError}</div>}
          </div>
        </section>
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
  return <div className="access-idle">Monitoring entrance continuously</div>
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

function accessSubtitle(mode: string, attempt: KioskStateResponse['active_access_attempt'], activeChatOwnerPresent: boolean) {
  if (activeChatOwnerPresent) return 'Access scan pauses while the verified chatbot owner is present'
  if (mode === 'chat-locked') return 'Owner away; door access remains active'
  if (mode === 'access-granted') return 'Entry decision confirmed'
  if (mode === 'access-denied' && attempt?.face_count) return 'Entry request denied'
  return 'Continuous face recognition is active'
}

function chatSubtitle(session: KioskStateResponse['active_chat_session'], cloudOnline: boolean, verifying: boolean) {
  if (verifying) return 'Verifying identity'
  if (!cloudOnline) return 'Chatbot cloud unavailable'
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
