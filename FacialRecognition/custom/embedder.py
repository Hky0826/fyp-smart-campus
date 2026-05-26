"""EdgeFace embedder that supports PyTorch (.pt/.pth) or ONNX models.

Prefer loading a scripted/traced PyTorch model (`.pt`, `.pth`) via `torch.jit.load`.
If the provided model is not a PyTorch artifact, the code will attempt to
use ONNX Runtime as a fallback for `.onnx` files.
"""

from __future__ import annotations

import gc
from typing import Tuple

import cv2
import numpy as np

try:
    import torch
    _HAS_TORCH = True
except Exception:
    _HAS_TORCH = False

try:
    import onnxruntime as ort
    _HAS_ONNXRT = True
except Exception:
    _HAS_ONNXRT = False


class EdgeFaceEmbedder:
    def __init__(self, model_path: str, device: str | None = None):
        self.model_path = model_path
        self.device = device
        self._use_torch = False
        self._use_onnx = False
        self.torch_model = None
        self.onnx_sess = None
        self.onnx_input = None

        if model_path.endswith('.pt') or model_path.endswith('.pth'):
            if not _HAS_TORCH:
                raise RuntimeError('PyTorch not available to load .pt model')
            # prefer torch.jit.load (supports scripted/traced models)
            dev = torch.device(device) if device is not None else torch.device('cpu')
            try:
                self.torch_model = torch.jit.load(model_path, map_location=dev)
            except Exception:
                # fallback to torch.load for state_dicts is not supported here
                raise RuntimeError('Failed to load scripted/traced PyTorch model. Provide a scripted/traced model (.pt)')
            self.torch_model.eval()
            self._use_torch = True
            self.torch_device = dev
        elif model_path.endswith('.onnx'):
            if not _HAS_ONNXRT:
                raise RuntimeError('onnxruntime not available to load .onnx model')
            self.onnx_sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
            self.onnx_input = self.onnx_sess.get_inputs()[0].name
            self._use_onnx = True
        else:
            # Try torch first if available, then onnx
            if _HAS_TORCH:
                try:
                    dev = torch.device(device) if device is not None else torch.device('cpu')
                    self.torch_model = torch.jit.load(model_path, map_location=dev)
                    self.torch_model.eval()
                    self._use_torch = True
                    self.torch_device = dev
                except Exception:
                    pass
            if not self._use_torch and _HAS_ONNXRT and model_path.endswith('.onnx'):
                self.onnx_sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
                self.onnx_input = self.onnx_sess.get_inputs()[0].name
                self._use_onnx = True
            if not (self._use_torch or self._use_onnx):
                raise RuntimeError('Unsupported model format or required runtime not available')

    @staticmethod
    def preprocess(crop: np.ndarray, target: Tuple[int, int] = (112, 112)) -> np.ndarray:
        img = cv2.resize(crop, target, interpolation=cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1)).astype(np.float32)
        img = np.expand_dims(img, axis=0)
        return img

    def embed(self, crop: np.ndarray) -> np.ndarray:
        pre = self.preprocess(crop)

        if self._use_torch:
            # Convert to torch tensor and run model
            x = torch.from_numpy(pre).to(self.torch_device)
            with torch.no_grad():
                out = self.torch_model(x)
            emb = out.detach().cpu().numpy().reshape(-1)
        elif self._use_onnx:
            out = self.onnx_sess.run(None, {self.onnx_input: pre})
            emb = np.asarray(out[0], dtype=np.float32).reshape(-1)
        else:
            raise RuntimeError('No backend available for embedding')

        # Zero-image enforcement: delete preprocess buffer
        try:
            del pre
        except Exception:
            pass
        gc.collect()

        # L2 normalize
        norm = np.linalg.norm(emb) + 1e-10
        emb = emb / norm
        return emb
