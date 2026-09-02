# Standalone Gemini Live + RAG System (`shitz` folder)

This is a **100% standalone, hands-free, full-duplex voice assistant** powered by **Gemini Live with Integrated RAG**.

### Features
- **Hands-Free Continuous Conversation**: No Enter key, no mute/unmute buttons. Speak naturally whenever you want.
- **Barge-In / Interruption Support**: If you speak while the assistant is speaking, it interrupts immediately and listens to your new statement.
- **Zero Server Startup**: Runs completely standalone without needing `uvicorn`, MySQL, or any backend servers.
- **Local In-Memory RAG Engine**: Indexes the 17 official QIU campus markdown documents from `documents/` (2,939 chunks) directly in memory.
- **Pulls Config from `.env`**: Automatically loads your `GOOGLE_API_KEY` from `cloud/dashboard/backend/.env`.

---

## How to Run

Run in PowerShell:

```powershell
.\.venv\Scripts\python.exe shitz\test_live.py
```

Once you see:
```
[Continuous Live Session Active]
Start talking now! Gemini Live is listening continuously (Press Ctrl+C to stop).
```
Just start speaking naturally! Gemini Live will listen, search the campus knowledge base in real-time when needed, and speak the grounded response back to you.
