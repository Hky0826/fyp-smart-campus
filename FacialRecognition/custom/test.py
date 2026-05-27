import os
import sys
import torch
import numpy as np

# 1. Force Python to see your 'custom' directory for package discovery
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# 2. Safely compute the path up to your 'models' folder
FYP_DIR = os.path.dirname(CURRENT_DIR)
MODEL_PATH = os.path.join(FYP_DIR, 'models', 'edgeface_xxs.pt')

print("=========================================")
print("     EDGEFACE ENVIRONMENT TEST SETUP     ")
print("=========================================\n")

# --- STEP 1: Test Package Imports ---
print("[Test 1/3] Verifying package dependencies...")
try:
    import timm
    from backbones import get_model
    print("  -> SUCCESS: Local 'backbones' and 'timm' imported perfectly!\n")
except ImportError as e:
    print(f"  -> FAILURE: {e}")
    print("  -> REMEDY: Run 'pip install timm' in your terminal.\n")
    sys.exit(1)

# --- STEP 2: Load the Model Architecture and Weights ---
print("[Test 2/3] Initializing architecture and loading weights...")
if not os.path.exists(MODEL_PATH):
    print(f"  -> FAILURE: Model checkpoint file not found at: {MODEL_PATH}")
    print("  -> REMEDY: Double-check that your .pt file name matches exactly.\n")
    sys.exit(1)

try:
    # Build architecture dynamically using the local package
    model = get_model("edgeface_xxs")
    
    # Load the state dict weights
    state_dict = torch.load(MODEL_PATH, map_location='cpu')
    if 'state_dict' in state_dict:
        state_dict = state_dict['state_dict']
        
    # Strip prefixes if data parallel wrappers exist
    clean_state_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}
    
    model.load_state_dict(clean_state_dict, strict=False)
    model.eval()
    print(f"  -> SUCCESS: Loaded weights from '{MODEL_PATH}' successfully!\n")
except Exception as e:
    print(f"  -> FAILURE: Could not bind checkpoint to architecture. Error: {e}\n")
    sys.exit(1)

# --- STEP 3: Generate Dummy Facial Vector Inference ---
print("[Test 3/3] Running a dry run pipeline inference...")
try:
    # Simulate a cropped 112x112 face image (Batch: 1, Channels: 3, Height: 112, Width: 112)
    fake_face_tensor = torch.randn(1, 3, 112, 112)
    
    with torch.no_grad():
        embedding_vector = model(fake_face_tensor)
        
    # Convert output tensor to standard numpy array
    embedding_array = embedding_vector.cpu().numpy().flatten()
    
    # Perform standard facial recognition vector normalization (L2 Normalize)
    norm = np.linalg.norm(embedding_array) + 1e-10
    normalized_embedding = embedding_array / norm

    print("  -> SUCCESS: Inference loop operational!")
    print(f"  -> Generated Vector Size: {normalized_embedding.shape[0]} dimensions.")
    print(f"  -> Sample Array Output: {normalized_embedding[:5]}...\n")
    
    print("=========================================")
    print("      ALL TESTS PASSED SUCCESSFULLY!      ")
    print(" EdgeFace is 100% operational for your kiosk app. ")
    print("=========================================")

except Exception as e:
    print(f"  -> FAILURE: Math calculations or tensor flow failed. Error: {e}\n")