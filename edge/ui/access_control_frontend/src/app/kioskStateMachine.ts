import type { AccessAttemptView, ChatSessionView, KioskStateResponse } from '../api/types'

export type KioskMode =
  | 'idle'
  | 'access-verifying'
  | 'access-granted'
  | 'access-denied'
  | 'chat-verifying'
  | 'chat-active'
  | 'chat-locked'
  | 'offline'

export interface LocalUiState {
  chatVerificationActive: boolean
  nowMs: number
}

export function deriveKioskMode(state: KioskStateResponse | null, local: LocalUiState): KioskMode {
  if (!state) {
    return 'offline'
  }

  const attempt = state.active_access_attempt
  if (attempt && !attempt.completed_at) {
    return 'access-verifying'
  }
  if (attempt && isRecentAttempt(attempt, state.timings.access_result_hold_seconds, local.nowMs)) {
    return attempt.access_decision === 'GRANTED' ? 'access-granted' : 'access-denied'
  }

  if (local.chatVerificationActive) {
    return 'chat-verifying'
  }

  const session = state.active_chat_session
  if (session?.locked) {
    return 'chat-locked'
  }
  if (session) {
    return 'chat-active'
  }

  return 'idle'
}

export function isChatContentSensitive(session: ChatSessionView | null | undefined): boolean {
  return Boolean(session?.locked || session?.presence_state === 'DIFFERENT_PERSON_PRESENT')
}

function isRecentAttempt(attempt: AccessAttemptView, holdSeconds: number, nowMs: number): boolean {
  if (!attempt.completed_at) {
    return false
  }
  const completedMs = Date.parse(attempt.completed_at)
  return Number.isFinite(completedMs) && nowMs - completedMs <= holdSeconds * 1000
}
