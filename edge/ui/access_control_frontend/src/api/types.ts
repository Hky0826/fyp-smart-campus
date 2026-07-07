export type PresenceState =
  | 'OWNER_PRESENT'
  | 'OWNER_TEMPORARILY_MISSING'
  | 'OWNER_LEFT'
  | 'DIFFERENT_PERSON_PRESENT'
  | 'UNKNOWN'

export type AccessDecision = 'PENDING' | 'VERIFYING' | 'GRANTED' | 'DENIED' | 'ERROR'

export interface KioskTimingConfig {
  owner_missing_grace_seconds: number
  owner_absent_lock_seconds: number
  owner_absent_terminate_seconds: number
  access_result_hold_seconds: number
}

export interface KioskDeviceStatus {
  edge_api: string
  cloud_chatbot: string
  device_id: string
  device_name: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  citations: Array<Record<string, unknown>>
}

export interface ChatSessionView {
  session_id: string
  authenticated_user_id: number
  username?: string | null
  full_name?: string | null
  roles: string[]
  cloud_session_id?: number | null
  owner_face_track_id?: string | null
  last_owner_seen_at?: string | null
  last_interaction_at: string
  presence_state: PresenceState
  expires_at?: string | null
  locked: boolean
  conversation_history: ChatMessage[]
}

export interface AccessAttemptView {
  attempt_id: string
  detected_user_id?: number | null
  door_id: string
  access_decision: AccessDecision
  reason?: string | null
  similarity?: number | null
  face_count: number
  created_at: string
  completed_at?: string | null
}

export interface KioskStateResponse {
  device: KioskDeviceStatus
  timings: KioskTimingConfig
  active_chat_session?: ChatSessionView | null
  active_access_attempt?: AccessAttemptView | null
}

export interface AccessRequestResponse {
  attempt: AccessAttemptView
}

export interface ChatVerifyResponse {
  session: ChatSessionView
}

export interface ChatMessageResponse {
  session: ChatSessionView
  answer: string
  citations: Array<Record<string, unknown>>
  access_granted: boolean
  status_message?: string | null
  response_time_ms?: number | null
  query_id?: number | null
}
