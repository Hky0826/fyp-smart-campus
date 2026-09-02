import os
import sys
import time
import asyncio
import requests
import json
import base64
import hashlib
import hmac
import secrets
import io
import wave
import threading
from pathlib import Path


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_request(method: str, path: str, query: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return "\n".join((method.upper(), path, query, timestamp, nonce, body_hash(body))).encode()


def sign_request(secret: str, method: str, path: str, query: str, timestamp: str, nonce: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), canonical_request(method, path, query, timestamp, nonce, body), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def sign_assertion(secret: str, assertion: dict) -> str:
    encoded = json.dumps(assertion, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(hmac.new(secret.encode(), encoded, hashlib.sha256).digest()).decode().rstrip("=")


def make_signed_request(secret: str, device_id: str, method: str, url: str, json_body: dict):
    body_bytes = json.dumps(json_body).encode()
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path
    query = parsed.query
    
    signature = sign_request(secret, method, path, query, timestamp, nonce, body_bytes)
    
    headers = {
        "x-device-id": device_id,
        "x-device-timestamp": timestamp,
        "x-device-nonce": nonce,
        "x-device-signature": signature,
        "Content-Type": "application/json"
    }
    
    if method.upper() == "POST":
        return requests.post(url, data=body_bytes, headers=headers)
    elif method.upper() == "GET":
        return requests.get(url, data=body_bytes, headers=headers)
    else:
        raise ValueError("Unsupported method")


def get_edge_token(server_url: str, device_id: str, device_secret: str, user_id: int) -> tuple[str, int]:
    print(f"Requesting face auth challenge for User ID {user_id}...")
    challenge_payload = {"user_id": user_id}
    resp = make_signed_request(
        device_secret, 
        device_id, 
        "POST", 
        f"{server_url}/api/edge-auth/challenge", 
        challenge_payload
    )
    if resp.status_code != 200:
        raise Exception(f"Failed to get challenge: {resp.text}")
        
    challenge_data = resp.json()
    challenge_id = challenge_data["challenge_id"]
    
    print("Generating simulated face match assertion...")
    assertion = {
        "challenge_id": challenge_id,
        "user_id": user_id,
        "match_passed": True,
        "liveness_passed": True,
        "pad_model_version": "simulated",
        "pad_score": 0.99
    }
    assertion_sig = sign_assertion(device_secret, assertion)
    
    token_payload = {
        "user_id": user_id,
        "device_id": device_id,
        "challenge_id": challenge_id,
        "assertion": assertion,
        "assertion_signature": assertion_sig
    }
    
    print("Exchanging assertion for Edge JWT Token...")
    resp = make_signed_request(
        device_secret,
        device_id,
        "POST",
        f"{server_url}/api/edge-auth/token",
        token_payload
    )
    if resp.status_code != 200:
        raise Exception(f"Failed to get token: {resp.text}")
        
    token_data = resp.json()
    return token_data["access_token"], token_data["session_id"]


def play_audio_response(pcm_or_wav_bytes: bytes, sample_rate: int = 24000):
    """Play received audio response via speaker."""
    if not pcm_or_wav_bytes:
        return
    try:
        import sounddevice as sd
        import numpy as np

        if pcm_or_wav_bytes.startswith(b"RIFF"):
            wav_io = io.BytesIO(pcm_or_wav_bytes)
            with wave.open(wav_io, "rb") as wf:
                sample_rate = wf.getframerate()
                pcm_data = wf.readframes(wf.getnframes())
        else:
            pcm_data = pcm_or_wav_bytes

        audio_array = np.frombuffer(pcm_data, dtype=np.int16)
        if audio_array.size > 0:
            sd.play(audio_array, samplerate=sample_rate)
            sd.wait()
    except Exception as exc:
        print(f"[Audio Playback Error] {exc}")


async def run_gemini_live_duplex_session(ws_url: str, token: str, device_id: str, session_id: int):
    """
    Full-duplex real-time Gemini Live WebSocket session.
    Streams microphone PCM chunks in real time and plays received audio chunks immediately.
    """
    import websockets
    import sounddevice as sd
    import numpy as np

    print(f"\nConnecting to Gemini Live WebSocket ({ws_url})...")
    async with websockets.connect(ws_url) as ws:
        # Wait for ready event
        init_msg = await ws.recv()
        init_data = json.loads(init_msg)
        print(f"[Gemini Live Connected] Ready: {init_data.get('data', {})}")

        while True:
            input("\nPress ENTER and speak naturally (Gemini Live is listening in real time)...")
            print("[Gemini Live Listening] Speak your question now... Press ENTER when done speaking.")
            
            stop_event = threading.Event()
            audio_queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def mic_callback(indata, frames, time_info, status):
                if not stop_event.is_set():
                    pcm_bytes = indata.tobytes()
                    loop.call_soon_threadsafe(audio_queue.put_nowait, pcm_bytes)

            input_stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="int16",
                blocksize=1600,  # 100ms chunks
                callback=mic_callback,
            )

            start_turn = time.monotonic()
            first_audio = False

            async def stream_mic_sender():
                with input_stream:
                    while not stop_event.is_set():
                        try:
                            pcm = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
                            await ws.send(pcm)
                        except asyncio.TimeoutError:
                            continue

            # Continuous audio output stream - keeps the soundcard open to prevent choppy/breaking audio
            output_stream = sd.RawOutputStream(
                samplerate=24000,
                channels=1,
                dtype="int16",
                blocksize=2400,
            )
            output_stream.start()

            async def receiver_loop():
                nonlocal first_audio
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg) if isinstance(msg, str) else {}
                    event = data.get("event")
                    event_data = data.get("data", {})

                    if event == "transcript":
                        print(f"\n[You]: \"{event_data.get('text', '')}\"")
                    elif event == "rag_status":
                        print(f"[Agentic RAG]: Searching authorized campus records...")
                    elif event == "rag_complete":
                        cits = [c.get('document_title') for c in event_data.get('citations', [])]
                        if cits:
                            print(f"[Citations]: {cits}")
                    elif event == "audio":
                        if not first_audio:
                            first_audio = True
                            ttfa = int((time.monotonic() - start_turn) * 1000)
                            print(f"[Time to First Audio (TTFA): {ttfa} ms]")
                        b64_chunk = event_data.get("chunk")
                        if b64_chunk:
                            raw_pcm = base64.b64decode(b64_chunk)
                            try:
                                await asyncio.to_thread(output_stream.write, raw_pcm)
                            except Exception:
                                pass
                    elif event == "output_transcript":
                        print(f"[Gemini Live]: {event_data.get('text', '')}")
                    elif event == "turn_complete":
                        total_ms = int((time.monotonic() - start_turn) * 1000)
                        print(f"[Turn Completed in {total_ms} ms]")
                        break

            # Launch streaming tasks
            sender_task = asyncio.create_task(stream_mic_sender())
            
            # Wait for user keypress to finish speaking
            def wait_stop():
                input()
                stop_event.set()

            stop_thread = threading.Thread(target=wait_stop)
            stop_thread.start()

            while not stop_event.is_set():
                await asyncio.sleep(0.05)

            sender_task.cancel()
            await ws.send(json.dumps({"event": "finish_turn"}))
            print("[Processing turn with Gemini Live...]")

            try:
                await receiver_loop()
            finally:
                try:
                    output_stream.stop()
                    output_stream.close()
                except Exception:
                    pass


def record_microphone_audio(sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Record audio from the microphone until Enter is pressed."""
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        print("[Notice] sounddevice/numpy not installed. Falling back to synthetic tone or file input.")
        return b""

    print("\n[Recording] Press ENTER to stop recording...")
    recorded_frames = []

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[Audio Status] {status}", file=sys.stderr)
        recorded_frames.append(indata.copy())

    stream = sd.InputStream(samplerate=sample_rate, channels=channels, dtype="int16", callback=callback)
    with stream:
        input()

    if not recorded_frames:
        return b""

    audio_data = np.concatenate(recorded_frames, axis=0)
    wav_io = io.BytesIO()
    with wave.open(wav_io, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())

    return wav_io.getvalue()


def main():
    print("=" * 65)
    print("Smart Campus Chatbot RBAC Tester (Gemini Live Duplex & Text Edge)")
    print("=" * 65)
    
    default_device_id = "ENTRY-A8F3D155"
    default_device_secret = "zeQsc02ket3dbVhfryNqynRra7OMo-mt8XLoaptDOrQLT0sW3d5EaitV8cfAZQwy"
    
    device_id = input(f"Enter Device ID [{default_device_id}]: ").strip() or default_device_id
    device_secret = input(f"Enter Device Secret [hidden]: ").strip() or default_device_secret
    
    print("\nAvailable RBACs:")
    print("1. ADMIN (UID 1)")
    print("2. STUDENT (UID 8)")
    print("3. LECTURER (UID 9)")
    print("4. STAFF (UID 15)")
    print("5. VISITOR (UID 14)")
    print("6. Custom User ID")
    
    rbac_choice = input("\nSelect RBAC (1-6) or type name directly [VISITOR]: ").strip().upper()
    
    target_uid = 14
    role_name = "VISITOR"
    if rbac_choice in ["1", "ADMIN"]:
        target_uid = 1
        role_name = "ADMIN"
    elif rbac_choice in ["2", "STUDENT"]:
        target_uid = 8
        role_name = "STUDENT"
    elif rbac_choice in ["3", "LECTURER"]:
        target_uid = 9
        role_name = "LECTURER"
    elif rbac_choice in ["4", "STAFF"]:
        target_uid = 15
        role_name = "STAFF"
    elif rbac_choice in ["5", "VISITOR"]:
        target_uid = 14
        role_name = "VISITOR"
    elif rbac_choice == "6":
        target_uid = int(input("Enter target User ID (int): ").strip())
        role_name = f"UID {target_uid}"
        
    server_url = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")

    access_token = None
    session_id = None
    
    print(f"\nAuthenticating Edge Device {device_id} as {role_name} (UID {target_uid})...")
    try:
        access_token, session_id = get_edge_token(server_url, device_id, device_secret, target_uid)
        print(f"Successfully obtained Edge Token! Session ID: {session_id}")
    except Exception as e:
        print(f"Failed to authenticate: {e}")
        return

    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    print("\nInteraction Modes:")
    print("1. Gemini Live Full-Duplex WebSocket (Real-Time Sub-Second Voice Streaming)")
    print("2. Batch Audio Mode (Record complete WAV and submit via HTTP)")
    print("3. Audio File Mode (Upload .wav file & listen to response)")
    print("4. Text Mode (Type questions & view JSON answer)")
    
    mode_choice = input("\nSelect mode (1/2/3/4) [1]: ").strip() or "1"
    print("-" * 65)

    if mode_choice == "1":
        ws_scheme = "wss" if server_url.startswith("https") else "ws"
        host = server_url.split("://")[-1]
        ws_url = f"{ws_scheme}://{host}/api/chatbot/live/ws?token={access_token or ''}&device_id={device_id}&session_id={session_id or ''}"
        try:
            asyncio.run(run_gemini_live_duplex_session(ws_url, access_token, device_id, session_id))
        except KeyboardInterrupt:
            print("\nSession ended.")
        except Exception as e:
            print(f"\n[Gemini Live WebSocket Error] {e}")
        return

    while True:
        if mode_choice == "2":
            input("\nPress ENTER and speak your question into the microphone...")
            audio_bytes = record_microphone_audio()
            if not audio_bytes:
                print("No audio captured. Try again.")
                continue

            files = {"audio": ("query.wav", audio_bytes, "audio/wav")}
            data = {"device_id": device_id}
            if session_id is not None:
                data["session_id"] = str(session_id)

            print("Sending audio to Cloud Agentic RAG (Batch)...", end="", flush=True)
            start_req = time.monotonic()
            try:
                resp = requests.post(
                    f"{server_url}/api/chatbot/chat/audio",
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=45,
                )
            except requests.RequestException as e:
                print(f"\n[Error] Connection failed: {e}")
                continue

            latency_ms = int((time.monotonic() - start_req) * 1000)
            print(f" HTTP {resp.status_code} ({latency_ms} ms)")

            if resp.status_code == 200:
                result = resp.json()
                print(f"\nTranscribed Input: \"{result.get('transcribed_input', '')}\"")
                print(f"Assistant Answer:  {result.get('text_response') or result.get('text', '')}")
                print(f"Access Granted:    {result.get('access_granted')}")
                if result.get('status_message'):
                    print(f"Status Message:    {result.get('status_message')}")
                if result.get('sources'):
                    print(f"Citations ({len(result.get('sources'))}): {[s.get('document_title') for s in result.get('sources')]}")

                b64_audio = result.get("audio_response") or result.get("audio_bytes")
                if b64_audio:
                    pcm_bytes = base64.b64decode(b64_audio)
                    play_audio_response(pcm_bytes)
            else:
                print(f"[Error] {resp.text}")

        elif mode_choice == "3":
            wav_path = input("\nEnter path to .wav file (or 'exit'): ").strip()
            if wav_path.lower() in ["exit", "quit"]:
                break
            p = Path(wav_path)
            if not p.exists():
                print(f"File not found: {wav_path}")
                continue

            with open(p, "rb") as f:
                audio_bytes = f.read()

            files = {"audio": (p.name, audio_bytes, "audio/wav")}
            data = {"device_id": device_id}
            if session_id is not None:
                data["session_id"] = str(session_id)

            print("Uploading audio file...", end="", flush=True)
            start_req = time.monotonic()
            try:
                resp = requests.post(
                    f"{server_url}/api/chatbot/chat/audio",
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=45,
                )
            except requests.RequestException as e:
                print(f"\n[Error] Connection failed: {e}")
                continue

            latency_ms = int((time.monotonic() - start_req) * 1000)
            print(f" HTTP {resp.status_code} ({latency_ms} ms)")

            if resp.status_code == 200:
                result = resp.json()
                print(f"\nTranscribed Input: \"{result.get('transcribed_input', '')}\"")
                print(f"Assistant Answer:  {result.get('text_response') or result.get('text', '')}")
                print(f"Access Granted:    {result.get('access_granted')}")
                b64_audio = result.get("audio_response") or result.get("audio_bytes")
                if b64_audio:
                    pcm_bytes = base64.b64decode(b64_audio)
                    play_audio_response(pcm_bytes)
            else:
                print(f"[Error] {resp.text}")

        else:
            query = input("\nYou (Text): ").strip()
            if not query:
                continue
            if query.lower() in ["quit", "exit"]:
                break

            payload = {
                "query": query,
                "device_id": device_id,
            }
            if session_id is not None:
                payload["session_id"] = session_id

            print("Sending request... ", end="", flush=True)
            start_req = time.monotonic()
            try:
                resp = requests.post(
                    f"{server_url}/api/chatbot/chat",
                    json=payload,
                    headers={"Content-Type": "application/json", **headers},
                    timeout=30,
                )
            except requests.RequestException as e:
                print(f"\n[Error] Connection failed: {e}")
                continue

            latency_ms = int((time.monotonic() - start_req) * 1000)
            print(f"HTTP {resp.status_code} ({latency_ms} ms)")

            if resp.status_code == 200:
                data = resp.json()
                print(f"\nChatbot: {data.get('answer', '')}")
                print(f"Access Granted: {data.get('access_granted')}")
                if data.get("citations"):
                    print(f"Citations: {[c.get('document_title') for c in data.get('citations')]}")
                nav = data.get("navigation_target")
                if nav:
                    print(f"[Navigation Triggered: {nav.get('label')}]")
            else:
                try:
                    err = resp.json()
                    print(f"\n[Error]: {err.get('detail', err)}")
                except Exception:
                    print(f"\n[Error]: {resp.text}")


if __name__ == "__main__":
    main()
