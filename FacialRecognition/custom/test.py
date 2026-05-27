import os
import sys
import torch

# Ensure backbones can be imported
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from backbones import get_model

# 1. Path definitions
FYP_DIR = os.path.dirname(SCRIPT_DIR)
INPUT_PT_PATH = os.path.join(FYP_DIR, '..', 'models', 'edgeface_xxs.pt')
OUTPUT_ONNX_PATH = os.path.join(FYP_DIR, '..', 'models', 'edgeface_xxs.onnx')

print(f"Loading weights from: {INPUT_PT_PATH}")

# 2. Rebuild and load the PyTorch model
model_name = "edgeface_xxs"
model = get_model(model_name)

# Handle raw state-dict mapping safely
state_dict = torch.load(INPUT_PT_PATH, map_location='cpu')
if 'state_dict' in state_dict:
    state_dict = state_dict['state_dict']

# Strip DataParallel prefix if present
clean_state_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}

model.load_state_dict(clean_state_dict, strict=False)
model.eval()

# 3. Create a dummy tensor matching EdgeFace input dimensions (Batch, Channels, Height, Width)
# EdgeFace expects a normalized 112x112 face crop
dummy_input = torch.randn(1, 3, 112, 112)

print("Exporting model to ONNX format...")

# 4. Export the network trace
torch.onnx.export(
    model, 
    dummy_input, 
    OUTPUT_ONNX_PATH, 
    export_params=True,        # Store the trained parameter weights inside the ONNX file
    opset_version=12,          # Standard, highly compatible ONNX operator version
    do_constant_folding=True,  # Optimizes network constants for faster speed
    input_names=['input'],     # Name of the input node
    output_names=['output'],   # Name of the output embedding node
    dynamic_axes={             # Allows the model to accept varying batch sizes during production
        'input': {0: 'batch_size'}, 
        'output': {0: 'batch_size'}
    }
)

print(f"Success! Your ONNX model is saved at: {OUTPUT_ONNX_PATH}")