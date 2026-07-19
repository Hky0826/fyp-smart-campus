"""ASGI entry point; models are constructed once per process."""
from .api import create_app
from .bootstrap import build_runtime
runtime=build_runtime()
app=create_app(runtime)