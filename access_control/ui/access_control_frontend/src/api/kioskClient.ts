import { API_BASE_URL } from '../app/config'
import type {
  AccessRequestResponse,
  ChatAudioResponse,
  ChatMessageResponse,
  ChatPresenceResponse,
  ChatVerifyResponse,
  KioskStateResponse
} from './types'

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers
    }
  })

  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: string }
      message = payload.detail || message
    } catch {
      // Keep status-based message.
    }
    throw new Error(message)
  }

  return response.json() as Promise<T>
}

export const kioskClient = {
  getState: () => requestJson<KioskStateResponse>('/kiosk/state'),

  requestAccess: () =>
    requestJson<AccessRequestResponse>('/kiosk/access/request', {
      method: 'POST'
    }),

  verifyAccessFrame: (frame: Blob) => {
    const body = new FormData()
    body.append('file', frame, 'access-frame.jpg')
    return requestJson<AccessRequestResponse>('/kiosk/access/frame', {
      method: 'POST',
      body
    })
  },

  verifyChatOwnerFrame: (frame: Blob) => {
    const body = new FormData()
    body.append('file', frame, 'chat-owner-frame.jpg')
    return requestJson<ChatVerifyResponse>('/kiosk/chat/verify/frame', {
      method: 'POST',
      body
    })
  },

  verifyChatPresenceFrame: (frame: Blob) => {
    const body = new FormData()
    body.append('file', frame, 'chat-presence-frame.jpg')
    return requestJson<ChatPresenceResponse>('/kiosk/chat/presence/frame', {
      method: 'POST',
      body
    })
  },

  sendChatMessage: (query: string) =>
    requestJson<ChatMessageResponse>('/kiosk/chat/message', {
      method: 'POST',
      body: JSON.stringify({ query })
    }),

  sendChatAudio: (audio: Blob) => {
    const body = new FormData()
    body.append('audio', audio, `chat-audio.${audio.type.includes('webm') ? 'webm' : 'wav'}`)
    return requestJson<ChatAudioResponse>('/kiosk/chat/audio', {
      method: 'POST',
      body
    })
  },

  lockChat: () =>
    requestJson<ChatVerifyResponse>('/kiosk/chat/lock', {
      method: 'POST'
    }),

  endChat: () =>
    requestJson<{ success: boolean }>('/kiosk/chat/end', {
      method: 'POST'
    }),

  stopChatAudio: () =>
    requestJson<{ success: boolean }>('/kiosk/chat/audio/stop', {
      method: 'POST'
    })
}

export function subscribeToKioskState(
  onState: (state: KioskStateResponse) => void,
  onError: () => void
): () => void {
  const events = new EventSource(`${API_BASE_URL}/kiosk/events`)
  events.addEventListener('state', (event) => {
    onState(JSON.parse((event as MessageEvent).data) as KioskStateResponse)
  })
  events.onerror = onError
  return () => events.close()
}
