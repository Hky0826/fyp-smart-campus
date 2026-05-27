import torch
from edgeface_architecture import EdgeFace # Replace with the actual architecture import

# 1. Initialize and load standard weights
model = EdgeFace() 
model.load_state_dict(torch.load("edgeface_xxs.pt", map_location="cpu"))
model.eval()

# 2. Create dummy input matching EdgeFace input dimensions (1, 3, 112, 112)
dummy_input = torch.rand(1, 3, 112, 112)

# 3. Trace the execution graph
traced_model = torch.jit.trace(model, dummy_input)

# 4. Save the compiled TorchScript artifact
traced_model.save("edgeface_xxs_traced.pt")
