import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from edge.facial_recognition.src.hailo import hailo_runner
from edge.facial_recognition.src.hailo.hailo_runner import HailoModelRunner


class FakeInfo:
    def __init__(self, name, shape=(1, 1, 1)):
        self.name = name
        self.shape = shape


class FakeHEF:
    def __init__(self, path):
        self.path = path

    def get_input_vstream_infos(self):
        return [FakeInfo("input")]

    def get_output_vstream_infos(self):
        return [FakeInfo("output")]


class FakeConfigureParams:
    @staticmethod
    def create_from_hef(hef, interface):
        return {"hef": hef, "interface": interface}


class FakeNetworkGroup:
    def create_params(self):
        return {}


class FakeVDevice:
    instances = 0

    def __init__(self):
        FakeVDevice.instances += 1

    def configure(self, hef, configure_params):
        return [FakeNetworkGroup()]


class FakeVStreamParams:
    @staticmethod
    def make(network_group, format_type):
        return {"network_group": network_group, "format_type": format_type}


class HailoRunnerTests(unittest.TestCase):
    def tearDown(self):
        hailo_runner._SHARED_VDEVICE = None
        FakeVDevice.instances = 0

    def test_model_runners_share_one_vdevice(self):
        fake_hailo_platform = types.SimpleNamespace(
            ConfigureParams=FakeConfigureParams,
            FormatType=types.SimpleNamespace(FLOAT32="float32"),
            HEF=FakeHEF,
            HailoStreamInterface=types.SimpleNamespace(PCIe="pcie"),
            InferVStreams=object,
            InputVStreamParams=FakeVStreamParams,
            OutputVStreamParams=FakeVStreamParams,
            VDevice=FakeVDevice,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            detector_path = Path(temp_dir) / "detector.hef"
            embedder_path = Path(temp_dir) / "embedder.hef"
            detector_path.write_bytes(b"fake")
            embedder_path.write_bytes(b"fake")

            with patch.dict(sys.modules, {"hailo_platform": fake_hailo_platform}):
                HailoModelRunner(detector_path)
                HailoModelRunner(embedder_path)

        self.assertEqual(FakeVDevice.instances, 1)


if __name__ == "__main__":
    unittest.main()
