"""
config/__init__.py
------------------
Configuration package for AI Services.

Exports:
    settings  — Application settings (from config.py via pydantic-settings)
    load_semantic_rules — Loads semantic_rules.yaml into the classifier format
"""
from src.config.semantic_rules_loader import load_semantic_rules

__all__ = ["load_semantic_rules"]
