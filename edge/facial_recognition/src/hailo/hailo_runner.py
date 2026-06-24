"""Generic Hailo HEF model runner."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

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
        "Install HailoRT for this exact Python environment on the EdgeMind device. "
        "If you are running in Docker, the container image must also include the "
        "HailoRT Python package; mapping /dev/hailo0 alone is not enough."
    )


class HailoModelRunner:
    """Thin HailoRT wrapper for single-input HEF inference."""

    def __init__(self, hef_path: str | Path) -> None:
        self.hef_path = Path(hef_path)
        if not self.hef_path.exists():
            raise FileNotFoundError(f"Missing Hailo HEF model: {self.hef_path}")

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
        except Exception as exc:  # pragma: no cover - depends on Hailo device image
            raise RuntimeError(hailort_import_error_message(exc)) from exc

        self._InferVStreams = InferVStreams
        self._InputVStreamParams = InputVStreamParams
        self._OutputVStreamParams = OutputVStreamParams
        self._FormatType = FormatType

        logger.info("Loading Hailo model: %s", self.hef_path)
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
        logger.info("Loaded %s input=%s shape=%s outputs=%s", self.hef_path.name, self.input_name, self.input_shape, self.output_names)

    def infer(self, input_tensor: np.ndarray, input_name: Optional[str] = None) -> Dict[str, np.ndarray]:
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
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Hailo inference failed for {self.hef_path.name}: {exc}") from exc


def _get_shared_vdevice(vdevice_cls):
    global _SHARED_VDEVICE
    with _VDEVICE_LOCK:
        if _SHARED_VDEVICE is None:
            try:
                _SHARED_VDEVICE = vdevice_cls()
            except Exception as exc:  # pragma: no cover - depends on Hailo device state
                raise RuntimeError(
                    "Failed to create Hailo VDevice. The accelerator may already be held by "
                    "another process, or this process may be trying to allocate more VDevices "
                    "than the hardware supports. Stop other edge/uvicorn/python Hailo "
                    f"processes and retry. Original HailoRT error: {exc}"
                ) from exc
        return _SHARED_VDEVICE
