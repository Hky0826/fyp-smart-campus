import {
  AlertTriangle,
  MessageSquare,
  X
} from 'lucide-react'
import type { MutableRefObject } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { kioskClient, subscribeToKioskState } from './api/kioskClient'
import type { ChatMessage, KioskStateResponse } from './api/types'
import { CAMERA_FRAME_INTERVAL_MS } from './app/config'
import { deriveKioskMode } from './app/kioskStateMachine'

const VOICE_RECORDING_MS = 5500
const VOICE_RESTART_DELAY_MS = 250
const TTS_OUTPUT_SAMPLE_RATE = 24000

function App() {
  const [state, setState] = useState<KioskStateResponse | null>(null)
  const [nowMs, setNowMs] = useState(Date.now())
  const [chatExpanded, setChatExpanded] = useState(false)
  const [chatVerificationActive, setChatVerificationActive] = useState(false)
  const [cameraReady, setCameraReady] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [chatError, setChatError] = useState<string | null>(null)
  const [voiceSupported, setVoiceSupported] = useState(true)
  const [voiceListening, setVoiceListening] = useState(false)
  const [voiceBusy, setVoiceBusy] = useState(false)
  const [transcriptPreview, setTranscriptPreview] = useState('')
  const [offline, setOffline] = useState(false)
  const [videoLayout, setVideoLayout] = useState({ width: 0, height: 0, videoWidth: 0, videoHeight: 0 })
  const [faceBoxes, setFaceBoxes] = useState<number[][]>([])
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const frameInFlightRef = useRef(false)
  const micStreamRef = useRef<MediaStream | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const voiceLoopTimeoutRef = useRef<number | null>(null)
  const voiceActiveRef = useRef(false)
  const audioContextRef = useRef<AudioContext | null>(null)
  const voiceQueueRef = useRef(Promise.resolve())

  const mode = deriveKioskMode(state, {
    chatVerificationActive,
    nowMs
  })

  const session = state?.active_chat_session ?? null
  const chatCameraMinimized = chatExpanded && Boolean(session) && !chatVerificationActive

  const stopVoiceRecording = useCallback(() => {
    voiceActiveRef.current = false
    if (voiceLoopTimeoutRef.current !== null) {
      window.clearTimeout(voiceLoopTimeoutRef.current)
      voiceLoopTimeoutRef.current = null
    }

    const recorder = mediaRecorderRef.current
    mediaRecorderRef.current = null
    if (recorder) {
      recorder.ondataavailable = null
      recorder.onerror = null
      recorder.onstop = null
      try {
        if (recorder.state !== 'inactive') {
          recorder.stop()
        }
      } catch {
        // Recorder may already be stopped by the browser.
      }
    }
    micStreamRef.current?.getTracks().forEach((track) => track.stop())
    micStreamRef.current = null
    setVoiceListening(false)
    setTranscriptPreview('')
  }, [])

  const sendVoiceAudio = useCallback((audio: Blob) => {
    if (audio.size < 1024) return
    voiceQueueRef.current = voiceQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        setVoiceBusy(true)
        try {
          const response = await kioskClient.sendChatAudio(audio)
          setState((current) => mergeChatSession(current, response.session))
          setTranscriptPreview('')
          if (response.audio_response) {
            await playPcmBase64(response.audio_response, audioContextRef)
          }
          setChatError(null)
        } catch (error) {
          setChatError(error instanceof Error ? error.message : 'Audio chatbot request failed.')
        } finally {
          setVoiceBusy(false)
        }
      })
  }, [])

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
            setState((current) => (current ? { ...current, active_chat_session: null, chat_recoverable: false } : current))
            setChatExpanded(false)
            setChatError(null)
            stopVoiceRecording()
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
  }, [cameraReady, chatVerificationActive, offline, session, stopVoiceRecording])

  useEffect(() => {
    if (!chatExpanded || !session || chatVerificationActive) {
      stopVoiceRecording()
      return
    }

    const getUserMedia = navigator.mediaDevices?.getUserMedia?.bind(navigator.mediaDevices)
    if (!getUserMedia || typeof MediaRecorder === 'undefined') {
      setVoiceSupported(false)
      return
    }

    let cancelled = false
    setVoiceSupported(true)

    async function startVoiceLoop() {
      try {
        const micStream = await getUserMedia({ audio: true, video: false })
        if (cancelled) {
          micStream.getTracks().forEach((track) => track.stop())
          return
        }

        micStreamRef.current = micStream
        voiceActiveRef.current = true

        const recordOnce = () => {
          if (!voiceActiveRef.current || !micStreamRef.current) return

          const chunks: Blob[] = []
          const options = pickAudioRecorderOptions()
          const recorder = options ? new MediaRecorder(micStreamRef.current, options) : new MediaRecorder(micStreamRef.current)
          mediaRecorderRef.current = recorder

          recorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
              chunks.push(event.data)
            }
          }
          recorder.onerror = () => {
            setChatError('Microphone recording failed.')
          }
          recorder.onstop = () => {
            if (!voiceActiveRef.current) return

            setVoiceListening(false)
            const mimeType = recorder.mimeType || 'audio/webm'
            const audioBlob = new Blob(chunks, { type: mimeType })
            if (audioBlob.size > 0) {
              sendVoiceAudio(audioBlob)
            }
            voiceLoopTimeoutRef.current = window.setTimeout(recordOnce, VOICE_RESTART_DELAY_MS)
          }

          recorder.start()
          setVoiceListening(true)
          voiceLoopTimeoutRef.current = window.setTimeout(() => {
            if (recorder.state !== 'inactive') {
              recorder.stop()
            }
          }, VOICE_RECORDING_MS)
        }

        recordOnce()
      } catch (error) {
        setVoiceSupported(false)
        setChatError(error instanceof Error ? error.message : 'Microphone is unavailable.')
      }
    }

    startVoiceLoop()

    return () => {
      cancelled = true
      stopVoiceRecording()
    }
  }, [chatExpanded, chatVerificationActive, sendVoiceAudio, session?.session_id, stopVoiceRecording])

  async function handleOpenChat() {
    setChatExpanded(true)
    if (!session && !chatVerificationActive) {
      await handleStartChat()
    }
  }

  async function handleExitChat() {
    stopVoiceRecording()
    setChatExpanded(false)
    setChatVerificationActive(false)
    setTranscriptPreview('')
    try {
      await kioskClient.endChat()
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Could not end chatbot session.')
    } finally {
      setState((current) => (current ? { ...current, active_chat_session: null, chat_recoverable: false } : current))
    }
  }

  async function handleStartChat() {
    setChatError(null)
    setCameraError(null)
    setChatVerificationActive(true)
    try {
      await kioskClient.stopChatAudio()
    } catch {
      // Browser audio chat can still start even if there is no audio output to stop.
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
              <button className="icon-button dark" onClick={handleExitChat} title="Exit chat">
                <X size={22} aria-label="Exit" />
              </button>
            </div>

            {session && (
              <>
                <ChatHistory
                  messages={session.conversation_history}
                  transcriptPreview={transcriptPreview}
                />
                <div
                  className={`voice-indicator ${voiceListening ? 'is-listening' : ''} ${voiceBusy ? 'is-busy' : ''}`}
                  aria-hidden="true"
                >
                  <span />
                  <span />
                  <span />
                </div>
              </>
            )}

            {(!voiceSupported || chatError) && (
              <div className="inline-alert" title={chatError ?? undefined}>
                <AlertTriangle size={22} aria-label={chatError ?? 'Voice transcription is unavailable'} />
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

function ChatHistory({
  messages,
  transcriptPreview
}: {
  messages: ChatMessage[]
  transcriptPreview: string
}) {
  const previewMessage: ChatMessage | null = transcriptPreview
    ? {
        role: 'user',
        content: transcriptPreview,
        created_at: 'voice-preview',
        citations: []
      }
    : null
  const visibleMessages = [...messages, ...(previewMessage ? [previewMessage] : [])]

  if (visibleMessages.length === 0) {
    return <div className="chat-history empty" />
  }
  return (
    <div className="chat-history">
      {visibleMessages.map((message, index) => (
        <article
          key={`${message.created_at}-${index}`}
          className={`message ${message.role} ${message.created_at === 'voice-preview' ? 'pending' : ''}`}
        >
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

function pickAudioRecorderOptions(): MediaRecorderOptions | undefined {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/wav'
  ]
  const mimeType = candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate))
  return mimeType ? { mimeType } : undefined
}

async function playPcmBase64(base64Pcm: string, audioContextRef: MutableRefObject<AudioContext | null>) {
  const binary = window.atob(base64Pcm)
  const pcm = new Int16Array(binary.length / 2)
  for (let index = 0; index < pcm.length; index += 1) {
    const lo = binary.charCodeAt(index * 2)
    const hi = binary.charCodeAt(index * 2 + 1)
    pcm[index] = (hi << 8) | lo
  }

  const AudioContextCtor = window.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AudioContextCtor) {
    throw new Error('Audio playback is unavailable in this browser.')
  }

  const context = audioContextRef.current ?? new AudioContextCtor({ sampleRate: TTS_OUTPUT_SAMPLE_RATE })
  audioContextRef.current = context
  if (context.state === 'suspended') {
    await context.resume()
  }

  const buffer = context.createBuffer(1, pcm.length, TTS_OUTPUT_SAMPLE_RATE)
  const channel = buffer.getChannelData(0)
  for (let index = 0; index < pcm.length; index += 1) {
    channel[index] = Math.max(-1, Math.min(1, pcm[index] / 32768))
  }

  const source = context.createBufferSource()
  source.buffer = buffer
  source.connect(context.destination)
  await new Promise<void>((resolve) => {
    source.onended = () => resolve()
    source.start()
  })
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
