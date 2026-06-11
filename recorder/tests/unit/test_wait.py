import pytest
from recorder_plugin.wait import WaitSpec


def test_wait_spec_rejects_custom_js():
    with pytest.raises(ValueError, match="custom_js is not supported"):
        WaitSpec.from_dict({"strategy": "custom_js", "js": "alert(1)"})


def test_wait_spec_accepts_selector():
    spec = WaitSpec.from_dict({"strategy": "selector", "selector": "h1", "state": "visible"})
    assert spec.strategy == "selector"
    assert spec.args == {"selector": "h1", "state": "visible"}


def test_wait_spec_accepts_text():
    spec = WaitSpec.from_dict({"strategy": "text", "text": "Saved", "exact": True})
    assert spec.strategy == "text"
    assert spec.args == {"text": "Saved", "exact": True}


def test_wait_spec_accepts_networkidle():
    spec = WaitSpec.from_dict({"strategy": "networkidle"})
    assert spec.strategy == "networkidle"
    assert spec.args == {}


def test_wait_spec_accepts_timeout():
    spec = WaitSpec.from_dict({"strategy": "timeout", "ms": 2000})
    assert spec.strategy == "timeout"
    assert spec.args == {"ms": 2000}


def test_wait_spec_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="Unknown wait strategy"):
        WaitSpec.from_dict({"strategy": "bongus"})
