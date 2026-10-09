"""Scaffold checks: packages import, config has the required keys, OpenCV is 5.x."""

from __future__ import annotations

import importlib

import cv2

from gaffer.config import load_config


def test_packages_import():
    for name in ("gaffer", "gaffer.config", "gaffer.llm", "gaffer.llm.bedrock_client",
                 "gaffer.perception", "gaffer.tactics", "gaffer.agent", "gaffer.api",
                 "gaffer.aws"):
        importlib.import_module(name)


def test_opencv_is_version_5():
    assert cv2.__version__.startswith("5.")


def test_config_has_model_and_region():
    cfg = load_config()
    assert cfg["aws"]["region"] == "ap-southeast-2"
    assert cfg["bedrock"]["model_id"] == "global.amazon.nova-2-lite-v1:0"
    assert cfg["bedrock"]["fallback_model_id"] == "apac.amazon.nova-micro-v1:0"
    assert cfg["seed"] == 42
