import os
import sys
import hashlib
import zipfile
import requests

MODELS_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_DIR = os.path.join(MODELS_DIR, "models")
os.makedirs(TARGET_DIR, exist_ok=True)

# URLs for models. ArcFace R50 must match the Hailo Model Zoo source used to
# compile edge/facial_recognition/models/surveillance/arcface_r50.hef.
MODELS = {
    "scrfd_10g.onnx": {
        "url": "https://huggingface.co/DIAMONIK7777/antelopev2/resolve/main/scrfd_10g_bnkps.onnx",
        "min_size": 1_000_000,
    },
    "arcface_r50.onnx": {
        "url": "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/FaceRecognition/arcface/arcface_r50/pretrained/2022-08-24/arcface_r50.zip",
        "archive_member": "r50.onnx",
        "sha256": "664c361bf352a3fc474168ca9def511b6178dd0040eda2e3b0229ae68d368390",
        "min_size": 100_000_000,
    },
}

def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def is_valid_model(path, spec):
    if not os.path.exists(path) or os.path.getsize(path) <= spec.get("min_size", 1_000_000):
        return False
    expected_sha256 = spec.get("sha256")
    return expected_sha256 is None or file_sha256(path) == expected_sha256

def download_file(url, dest_path):
    print(f"Downloading {url} to {dest_path}...")
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        sys.stdout.write(f"\rProgress: {percent:.2f}% ({downloaded}/{total_size} bytes)")
                        sys.stdout.flush()
        print("\nDownload complete.")
        return True
    except Exception as e:
        print(f"\nFailed to download: {e}")
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False

def extract_archive_member(archive_path, member_name, dest_path):
    try:
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open(member_name) as src, open(dest_path, "wb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(chunk)
        return True
    except Exception as e:
        print(f"\nFailed to extract {member_name}: {e}")
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False

def main():
    success = True
    for name, spec in MODELS.items():
        dest_path = os.path.join(TARGET_DIR, name)
        if is_valid_model(dest_path, spec):
            print(f"Model {name} already exists at {dest_path} and is valid. Skipping download.")
        else:
            archive_member = spec.get("archive_member")
            if archive_member:
                archive_path = dest_path + ".zip"
                downloaded = download_file(spec["url"], archive_path)
                extracted = downloaded and extract_archive_member(archive_path, archive_member, dest_path)
                if os.path.exists(archive_path):
                    os.remove(archive_path)
                ok = extracted and is_valid_model(dest_path, spec)
            else:
                ok = download_file(spec["url"], dest_path) and is_valid_model(dest_path, spec)
            if not ok:
                success = False
                
    if success:
        print("All ONNX models verified successfully!")
        sys.exit(0)
    else:
        print("Some ONNX models failed to download.")
        sys.exit(1)

if __name__ == "__main__":
    main()
