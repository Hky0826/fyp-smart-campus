import os
import sys
import time
import requests
import json
import base64
import hashlib
import hmac
import secrets

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


def main():
    print("="*60)
    print("Chatbot RBAC Text-Only Tester (Edge Client Simulation)")
    print("="*60)
    
    default_device_id = "ENTRY-A8F3D155"
    default_device_secret = "zeQsc02ket3dbVhfryNqynRra7OMo-mt8XLoaptDOrQLT0sW3d5EaitV8cfAZQwy"
    
    device_id = input(f"Enter Device ID [{default_device_id}]: ").strip() or default_device_id
    device_secret = input(f"Enter Device Secret [hidden]: ").strip() or default_device_secret
    
    print("\nAvailable RBACs:")
    print("1. ADMIN (UID 1)")
    print("2. STUDENT (UID 8)")
    print("3. LECTURER (UID 9)")
    print("4. STAFF (UID 15)")
    print("5. VISITOR")
    print("6. Custom User ID")
    
    rbac_choice = input("\nSelect RBAC (1-6) or type name directly [VISITOR]: ").strip().upper()
    
    target_uid = None
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
    else:
        # Default to visitor if they type something weird
        target_uid = 14
        role_name = "VISITOR"
        
    server_url = os.getenv("SERVER_URL","http://localhost:8000").rstrip("/")
    #server_url = os.getenv("SERVER_URL", "https://smart-campus-cloud-1023040236733.asia-southeast1.run.app").rstrip("/")

    access_token = None
    session_id = None
    
    print(f"\nAuthenticating Edge Device {device_id} as {role_name} (UID {target_uid})...")
    try:
        access_token, session_id = get_edge_token(server_url, device_id, device_secret, target_uid)
        print(f"Successfully obtained Edge Token! Session ID: {session_id}")
    except Exception as e:
        print(f"Failed to authenticate: {e}")
        return

    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    print(f"\nReady! Target URL: {server_url}/api/chatbot/chat")
    print("Type your query below. Type 'quit' or 'exit' to stop.")
    print("-" * 60)

    while True:
        query = input("\nYou: ").strip()
        if not query:
            continue
        if query.lower() in ['quit', 'exit']:
            break
            
        payload = {
            "query": query,
            "device_id": device_id,
        }
        if session_id is not None:
            payload["session_id"] = session_id
            
        print("Sending request... ", end="", flush=True)
        try:
            resp = requests.post(
                f"{server_url}/api/chatbot/chat",
                json=payload,
                headers=headers,
                timeout=30
            )
        except requests.RequestException as e:
            print(f"\n[Error] Connection failed: {e}")
            continue
            
        print(f"Response: HTTP {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"\nChatbot: {data.get('answer', '')}")
            
            nav = data.get('navigation_target')
            if nav:
                print(f"[Navigation Triggered: {nav.get('label')}]")
                

        else:
            try:
                err = resp.json()
                print(f"\n[Error]: {err.get('detail', err)}")
            except:
                print(f"\n[Error]: {resp.text}")

if __name__ == "__main__":
    main()
