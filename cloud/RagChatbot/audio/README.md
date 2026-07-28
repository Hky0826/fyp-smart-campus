# Greeting recordings

To avoid synthesizing the fixed portion of the post-verification greeting,
place these mono, 16-bit, 24 kHz PCM WAV files in this directory (or set
`RAG_GREETING_AUDIO_DIR` to another directory):

- `greeting_generic.wav`: `Hi, how may I help you today?`
- `greeting_hi.wav`: `Hi`
- `greeting_suffix.wav`: `, how may I help you today?`

The authenticated path synthesizes only the user's given name and joins it
between the prefix and suffix. If any required file is absent or has a
different format, the service falls back to the existing full-greeting TTS.
