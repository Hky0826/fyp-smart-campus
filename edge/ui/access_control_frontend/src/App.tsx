import {
  AlertTriangle,
  MessageSquare,
  X
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
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
  const [chatError, setChatError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [videoLayout, setVideoLayout] = useState({ width: 0, height: 0, videoWidth: 0, videoHeight: 0 })
  const [faceBoxes, setFaceBoxes] = useState<number[][]>([])
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const frameInFlightRef = useRef(false)

  const mode = deriveKioskMode(state, {
    chatVerificationActive,
    nowMs
  })

  const session = state?.active_chat_session ?? null
  const chatRecoverable = Boolean(state?.chat_recoverable)
  const chatCameraMinimized = chatExpanded && Boolean(session) && !chatVerificationActive

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
          updateVideoLayout(videoRef.current, setVideoLayout)
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
    const update = () => {
      if (videoRef.current) {
        updateVideoLayout(videoRef.current, setVideoLayout)
      }
    }
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
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
      updateVideoLayout(videoRef.current, setVideoLayout)

      frameInFlightRef.current = true
      try {
        if (chatVerificationActive) {
          const response = await kioskClient.verifyChatOwnerFrame(frame)
          setState((current) => mergeChatSession(current, response.session))
          setFaceBoxes(response.bboxes)
          setChatVerificationActive(false)
          setChatError(null)
          return
        }

        if (session) {
          const presence = await kioskClient.verifyChatPresenceFrame(frame)
          setFaceBoxes(presence.bboxes)
          if (presence.ended) {
            setState((current) => (current ? { ...current, active_chat_session: null, chat_recoverable: true } : current))
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
            setFaceBoxes(accessResponse.attempt.bboxes)
          }
          return
        }

        if (chatRecoverable) {
          const recovery = await kioskClient.reopenChatFrame(frame)
          setFaceBoxes(recovery.bboxes)
          const recoverySession = recovery.session
          if (recovery.owner_present && recoverySession) {
            setState((current) => mergeChatSession(current, recoverySession))
            setChatExpanded(true)
            setChatError(null)
            return
          }
        }

        const accessResponse = await kioskClient.verifyAccessFrame(frame)
        setState((current) => mergeAccessAttempt(current, accessResponse.attempt))
        setFaceBoxes(accessResponse.attempt.bboxes)
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
  }, [cameraReady, chatRecoverable, chatVerificationActive, offline, session])

  async function handleOpenChat() {
    setChatExpanded(true)
    if (!session && !chatVerificationActive) {
      await handleStartChat()
    }
  }

  async function handleStartChat() {
    setChatError(null)
    setCameraError(null)
    setChatVerificationActive(true)
    try {
      await kioskClient.stopChatAudio()
    } catch {
      // Browser text chat can still start even if there is no audio output to stop.
    }
  }

  return (
    <main className={`kiosk-shell ${accessBorderClass(mode)} ${chatCameraMinimized ? 'has-minimized-camera' : ''}`}>
      <section className={`camera-fullscreen ${chatCameraMinimized ? 'is-minimized' : ''}`}>
        <video ref={videoRef} className="camera-feed" playsInline muted />
        <FaceBoxes boxes={faceBoxes} layout={videoLayout} />
        <div className="camera-shade" />
      </section>

      <button className="chat-launcher" onClick={handleOpenChat} disabled={!cameraReady || offline} title="Chatbot">
        <MessageSquare size={30} aria-label="Chatbot" />
      </button>

      {chatExpanded && (
        <section className={`chat-overlay ${chatVerificationActive ? 'is-verifying' : ''}`}>
          <div className="chat-window">
            <div className="chat-header">
              <MessageSquare size={24} aria-label="Chatbot" />
              <button className="icon-button dark" onClick={() => setChatExpanded(false)} title="Collapse chat">
                <X size={22} aria-label="Close" />
              </button>
            </div>

            {session && <ChatHistory messages={session.conversation_history} />}

            {chatError && (
              <div className="inline-alert" title={chatError}>
                <AlertTriangle size={22} aria-label={chatError} />
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  )
}

function accessBorderClass(mode: string) {
  if (mode === 'access-granted') return 'access-granted-border'
  if (mode === 'access-denied') return 'access-denied-border'
  return ''
}

function ChatHistory({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return <div className="chat-history empty" />
  }
  return (
    <div className="chat-history">
      {messages.map((message, index) => (
        <article key={`${message.created_at}-${index}`} className={`message ${message.role}`}>
          <p>{message.content}</p>
        </article>
      ))}
    </div>
  )
}

function FaceBoxes({ boxes, layout }: { boxes: number[][]; layout: { width: number; height: number; videoWidth: number; videoHeight: number } }) {
  if (!boxes.length || !layout.width || !layout.height || !layout.videoWidth || !layout.videoHeight) {
    return null
  }

  return (
    <div className="face-box-layer">
      {boxes.map((box, index) => {
        const rect = mapMirroredCoverBox(box, layout)
        if (!rect) return null
        return (
          <div
            className="face-box"
            key={`${box.join('-')}-${index}`}
            style={{
              left: `${rect.left}px`,
              top: `${rect.top}px`,
              width: `${rect.width}px`,
              height: `${rect.height}px`
            }}
          />
        )
      })}
    </div>
  )
}

function mergeAccessAttempt(current: KioskStateResponse | null, attempt: NonNullable<KioskStateResponse['active_access_attempt']>) {
  if (!current) return current
  return { ...current, active_access_attempt: attempt }
}

function mergeChatSession(current: KioskStateResponse | null, session: NonNullable<KioskStateResponse['active_chat_session']>) {
  if (!current) return current
  return { ...current, active_chat_session: session, chat_recoverable: false }
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

function updateVideoLayout(video: HTMLVideoElement, setLayout: (layout: { width: number; height: number; videoWidth: number; videoHeight: number }) => void) {
  const rect = video.getBoundingClientRect()
  setLayout({
    width: rect.width,
    height: rect.height,
    videoWidth: video.videoWidth,
    videoHeight: video.videoHeight
  })
}

function mapMirroredCoverBox(
  box: number[],
  layout: { width: number; height: number; videoWidth: number; videoHeight: number }
): { left: number; top: number; width: number; height: number } | null {
  if (box.length < 4) return null
  const [x1, y1, x2, y2] = box
  const scale = Math.max(layout.width / layout.videoWidth, layout.height / layout.videoHeight)
  const drawnWidth = layout.videoWidth * scale
  const drawnHeight = layout.videoHeight * scale
  const offsetX = (layout.width - drawnWidth) / 2
  const offsetY = (layout.height - drawnHeight) / 2

  return {
    left: offsetX + (layout.videoWidth - x2) * scale,
    top: offsetY + y1 * scale,
    width: Math.max(0, (x2 - x1) * scale),
    height: Math.max(0, (y2 - y1) * scale)
  }
}

export default App
