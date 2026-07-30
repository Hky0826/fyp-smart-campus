"""Hailo HEF model runner and manager for the surveillance module."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple, Any

import numpy as np

logger = logging.getLogger(__name__)

_VDEVICE_LOCK = threading.Lock()
_INFER_LOCK = threading.Lock()
_SHARED_VDEVICE = None


def hailort_import_error_message(exc: BaseException) -> str:
    return (
        "Could not import HailoRT Python bindings (`hailo_platform`). "
        f"Python executable: {sys.executable}. "
        f"Original import error: {exc!r}. "
        "Install HailoRT for this exact Python environment on the Hailo-equipped device."
    )


class BaseHailoRunner:
    """Interface for Hailo model execution."""

    def infer(self, input_tensor: np.ndarray, input_name: Optional[str] = None) -> Dict[str, np.ndarray]:
        raise NotImplementedError


class MockHailoModelRunner(BaseHailoRunner):
    """Mock runner for testing or placeholder mode when HEF files are absent."""

    def __init__(self, model_name: str, input_shape: Tuple[int, ...] = (1, 3, 640, 640)) -> None:
        self.model_name = model_name
        self.input_name = "input_0"
        self.input_shape = input_shape
        self.is_mock = True
        logger.warning("Using MockHailoModelRunner for %s (no physical HEF loaded)", model_name)

    def infer(self, input_tensor: np.ndarray, input_name: Optional[str] = None) -> Dict[str, np.ndarray]:
        # Return mock outputs depending on the model name
        if "yolox" in self.model_name.lower():
            # Return dummy YOLOX detection output
            return {"output_0": np.zeros((1, 8400, 85), dtype=np.float32)}
        elif "yunet" in self.model_name.lower():
            # Return dummy YuNet detection output
            return {"output_0": np.zeros((1, 100, 15), dtype=np.float32)}
        elif "auraface" in self.model_name.lower():
            # Return 512-d zero vector or random vector normalized
            vec = np.ones((1, 512), dtype=np.float32)
            vec /= np.linalg.norm(vec)
            return {"output_0": vec}
        return {"output_0": np.zeros((1, 10), dtype=np.float32)}


class HailoModelRunner(BaseHailoRunner):
    """HailoRT wrapper for HEF model inference."""

    def __init__(self, hef_path: str | Path, allow_mock: bool = True) -> None:
        self.hef_path = Path(hef_path)
        self.is_mock = False

        if not self.hef_path.exists():
            if allow_mock:
                logger.warning(
                    "HEF model file not found at '%s'. Falling back to MockHailoModelRunner.",
                    self.hef_path,
                )
                self._mock_runner = MockHailoModelRunner(self.hef_path.name)
                self.is_mock = True
                self.input_name = self._mock_runner.input_name
                self.input_shape = self._mock_runner.input_shape
                return
            else:
                raise FileNotFoundError(f"Missing Hailo HEF model file: {self.hef_path}")

        try:
            from hailo_platform import (  # type: ignore
                ConfigureParams,
                FormatType,
                HEF,
                HailoStreamInterface,
                InferVStreams,
                InputVStreamParams,
                OutputVStreamParams,
                VDevice,
            )
        except Exception as exc:
            if allow_mock:
                logger.warning(
                    "HailoRT unavailable (%s). Falling back to MockHailoModelRunner for %s.",
                    exc,
                    self.hef_path.name,
                )
                self._mock_runner = MockHailoModelRunner(self.hef_path.name)
                self.is_mock = True
                self.input_name = self._mock_runner.input_name
                self.input_shape = self._mock_runner.input_shape
                return
            raise RuntimeError(hailort_import_error_message(exc)) from exc

        self._InferVStreams = InferVStreams
        self._InputVStreamParams = InputVStreamParams
        self._OutputVStreamParams = OutputVStreamParams
        self._FormatType = FormatType

        logger.info("Loading Hailo HEF model: %s", self.hef_path)
        try:
            self.hef = HEF(str(self.hef_path))
            self.vdevice = _get_shared_vdevice(VDevice)
            configure_params = ConfigureParams.create_from_hef(
                self.hef,
                interface=HailoStreamInterface.PCIe,
            )
            self.network_group = self.vdevice.configure(self.hef, configure_params)[0]
            self.network_group_params = self.network_group.create_params()
            self.input_vstreams_params = InputVStreamParams.make(
                self.network_group,
                format_type=FormatType.FLOAT32,
            )
            self.output_vstreams_params = OutputVStreamParams.make(
                self.network_group,
                format_type=FormatType.FLOAT32,
            )

            input_infos = self.hef.get_input_vstream_infos()
            if not input_infos:
                raise RuntimeError(f"HEF has no input streams: {self.hef_path}")
            self.input_name = input_infos[0].name
            self.input_shape = tuple(input_infos[0].shape)
            self.output_names = [info.name for info in self.hef.get_output_vstream_infos()]
            logger.info(
                "Successfully initialized HEF model %s: input=%s shape=%s outputs=%s",
                self.hef_path.name,
                self.input_name,
                self.input_shape,
                self.output_names,
            )
        except Exception as exc:
            if allow_mock:
                logger.warning(
                    "Failed to initialize Hailo device/stream for %s (%s). Falling back to mock.",
                    self.hef_path.name,
                    exc,
                )
                self._mock_runner = MockHailoModelRunner(self.hef_path.name)
                self.is_mock = True
                self.input_name = self._mock_runner.input_name
                self.input_shape = self._mock_runner.input_shape
            else:
                raise RuntimeError(f"Failed to load HEF model {self.hef_path}: {exc}") from exc

    def infer(self, input_tensor: np.ndarray, input_name: Optional[str] = None) -> Dict[str, np.ndarray]:
        if self.is_mock:
            return self._mock_runner.infer(input_tensor, input_name=input_name)

        name = input_name or self.input_name
        inputs = {name: input_tensor.astype(np.float32, copy=False)}
        try:
            with _INFER_LOCK:
                with self.network_group.activate(self.network_group_params):
                    with self._InferVStreams(
                        self.network_group,
                        self.input_vstreams_params,
                        self.output_vstreams_params,
                    ) as infer_pipeline:
                        return infer_pipeline.infer(inputs)
        except Exception as exc:
            raise RuntimeError(f"Hailo inference failed for {self.hef_path.name}: {exc}") from exc


def _get_shared_vdevice(vdevice_cls: Any) -> Any:
    global _SHARED_VDEVICE
    with _VDEVICE_LOCK:
        if _SHARED_VDEVICE is None:
            try:
                _SHARED_VDEVICE = vdevice_cls()
            except Exception as exc:
                raise RuntimeError(
                    "Failed to create Hailo VDevice. Device may be in use by another process. "
                    f"Original error: {exc}"
                ) from exc
        return _SHARED_VDEVICE


class HailoModelManager:
    """Manages lifecycle and loading of multiple HEF models."""

    def __init__(self, allow_mock: bool = True) -> None:
        self.allow_mock = allow_mock
        self.runners: Dict[str, BaseHailoRunner] = {}

    def load_model(self, model_key: str, path: str | Path) -> BaseHailoRunner:
        path = Path(path)
        logger.info("HailoModelManager loading model '%s' from %s", model_key, path)
        runner = HailoModelRunner(path, allow_mock=self.allow_mock)
        self.runners[model_key] = runner
        return runner

    def get_runner(self, model_key: str) -> Optional[BaseHailoRunner]:
        return self.runners.get(model_key)
