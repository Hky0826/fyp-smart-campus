"""EdgeFace embedder that supports PyTorch (.pt/.pth) or ONNX models.

Prefer loading a scripted/traced PyTorch model (`.pt`, `.pth`) via `torch.jit.load`.
If the provided model is not a PyTorch artifact, the code will attempt to
use ONNX Runtime as a fallback for `.onnx` files.

This loader also supports standard state-dict checkpoints when a local
`backbones.get_model` builder is available.
"""

from __future__ import annotations

import gc
import os
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

try:
    # Support both package and script execution
    if __package__:
        from .backbones import get_model as _get_model
    else:
        from backbones import get_model as _get_model
    _HAS_BACKBONES = True
except Exception:
    _HAS_BACKBONES = False
    _get_model = None


class EdgeFaceEmbedder:
    def __init__(
        self,
        model_path: str,
        device: str | None = None,
        model_name: str | None = None,
        checkpoint_path: str | None = None,
    ):
        self.model_path = model_path
        self.device = device
        self.model_name = model_name
        self.checkpoint_path = checkpoint_path or model_path
        self._use_torch = False
        self._use_onnx = False
        self.torch_model = None
        self.onnx_sess = None
        self.onnx_input = None
        self.preprocess_mode = 'edgeface'

        if self.checkpoint_path.endswith('.pt') or self.checkpoint_path.endswith('.pth'):
            if not _HAS_TORCH:
                raise RuntimeError('PyTorch not available to load .pt model')
            self._init_torch_backend()
        elif self.checkpoint_path.endswith('.onnx'):
            if not _HAS_ONNXRT:
                raise RuntimeError('onnxruntime not available to load .onnx model')
            self.onnx_sess = ort.InferenceSession(self.checkpoint_path, providers=['CPUExecutionProvider'])
            self.onnx_input = self.onnx_sess.get_inputs()[0].name
            self._use_onnx = True
        else:
            # Try torch first if available, then onnx
            if _HAS_TORCH:
                try:
                    self._init_torch_backend()
                except Exception:
                    pass
            if not self._use_torch and _HAS_ONNXRT and self.checkpoint_path.endswith('.onnx'):
                self.onnx_sess = ort.InferenceSession(self.checkpoint_path, providers=['CPUExecutionProvider'])
                self.onnx_input = self.onnx_sess.get_inputs()[0].name
                self._use_onnx = True
            if not (self._use_torch or self._use_onnx):
                raise RuntimeError('Unsupported model format or required runtime not available')

    def _init_torch_backend(self) -> None:
        """Initialize torch backend with TorchScript-first, then state-dict fallback."""
        dev = torch.device(self.device) if self.device is not None else torch.device('cpu')

        # 1) Prefer TorchScript/traced artifacts (existing behavior)
        try:
            self.torch_model = torch.jit.load(self.checkpoint_path, map_location=dev)
            self.torch_model.eval()
            self._use_torch = True
            self.torch_device = dev
            return
        except Exception:
            pass

        # 2) Fallback: regular torch.load checkpoint + local architecture builder
        ckpt = torch.load(self.checkpoint_path, map_location=dev)

        # If checkpoint is already a module, use it directly
        if hasattr(torch, 'nn') and isinstance(ckpt, torch.nn.Module):
            self.torch_model = ckpt.to(dev)
            self.torch_model.eval()
            self._use_torch = True
            self.torch_device = dev
            return

        # If checkpoint is a state dict, load via backbones.get_model(model_name)
        if isinstance(ckpt, dict):
            if not _HAS_BACKBONES or _get_model is None:
                raise RuntimeError(
                    'Checkpoint appears to be a state dict. Add local backbones.get_model support '
                    'or provide a TorchScript model.'
                )

            resolved_name = self.model_name or self._infer_model_name(self.checkpoint_path)
            if not resolved_name:
                raise RuntimeError('Unable to infer model_name; please pass model_name explicitly')

            model = _get_model(resolved_name)
            state_dict = self._extract_state_dict(ckpt)

            try:
                model.load_state_dict(state_dict, strict=True)
            except Exception:
                # Common fallback for checkpoints with wrapper prefixes
                stripped = self._strip_module_prefix(state_dict)
                model.load_state_dict(stripped, strict=False)

            self.torch_model = model.to(dev)
            self.torch_model.eval()
            self._use_torch = True
            self.torch_device = dev
            return

        raise RuntimeError('Unsupported PyTorch checkpoint format')

    @staticmethod
    def _extract_state_dict(ckpt: dict) -> dict:
        """Extract state dict from common checkpoint layouts."""
        for key in ('state_dict', 'model_state_dict', 'model'):
            value = ckpt.get(key)
            if isinstance(value, dict):
                return value
        return ckpt

    @staticmethod
    def _strip_module_prefix(state_dict: dict) -> dict:
        """Strip leading 'module.' prefix from keys when checkpoint came from DataParallel."""
        out = {}
        for k, v in state_dict.items():
            if isinstance(k, str) and k.startswith('module.'):
                out[k[7:]] = v
            else:
                out[k] = v
        return out

    @staticmethod
    def _infer_model_name(path: str) -> str | None:
        """Infer model name from checkpoint filename, e.g. edgeface_xs_gamma_06.pt."""
        stem = os.path.splitext(os.path.basename(path))[0]
        return stem or None

    @staticmethod
    def preprocess(crop: np.ndarray, target: Tuple[int, int] = (112, 112)) -> np.ndarray:
        # Equivalent to torchvision pipeline:
        # Resize -> ToTensor -> Normalize(mean=.5,std=.5)
        img = cv2.resize(crop, target, interpolation=cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = (img - 0.5) / 0.5
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
