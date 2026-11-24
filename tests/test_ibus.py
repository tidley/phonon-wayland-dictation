"""Destination routing and native-output failure semantics."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from phonon_dictation import app, ibus


@pytest.mark.parametrize("error", [FileNotFoundError(), ConnectionRefusedError()])
def test_auto_uses_clipboard_when_helper_is_not_running(monkeypatch, error):
    def missing(*args, **kwargs):
        raise error
    monkeypatch.setattr(ibus, "request", missing)
    assert ibus.begin("auto") is None
    with pytest.raises(ibus.IBusError, match="Select Phonon"):
        ibus.begin("ibus")


def test_auto_does_not_fallback_when_phonon_is_selected_without_a_text_field(monkeypatch):
    monkeypatch.setattr(ibus, "request", lambda *_: {"ok": False, "selected": True, "error": "No focused input field"})
    with pytest.raises(ibus.IBusError, match="No focused"):
        ibus.begin("auto")


def test_auto_uses_clipboard_when_another_source_is_selected(monkeypatch):
    monkeypatch.setattr(ibus, "request", lambda *_: {"ok": False, "selected": False})
    assert ibus.begin("auto") is None


def test_begin_reserves_a_target_and_commit_preserves_request_identity(monkeypatch):
    calls = []
    def request(message, **kwargs):
        calls.append(message)
        if message["op"] == "begin":
            return {"ok": True, "token": "helper:field:1", "request_id": "recording-1", "context": "/field"}
        return {"ok": True, "status": "emitted"}
    monkeypatch.setattr(ibus, "request", request)
    target = ibus.begin("ibus")
    ibus.commit(target, "Native café")
    assert calls == [{"op": "begin"}, {"op": "commit", "request_id": "recording-1", "token": "helper:field:1", "text": "Native café "}]


@pytest.mark.parametrize("response", [
    {"ok": False, "error": "Focus changed"},
    {"ok": False, "error": "Previous delivery uncertain"},
])
def test_failed_native_commit_never_calls_clipboard_or_retries(monkeypatch, tmp_path, response, capsys):
    path = tmp_path / "capture.wav"
    path.write_bytes(b"x" * 2000)
    process = SimpleNamespace(returncode=255, wait=lambda timeout: None)
    calls = []
    monkeypatch.setattr(app, "suspend_offset", lambda: 0)
    monkeypatch.setattr(app, "transcribe", lambda *_: "private speech")
    monkeypatch.setattr(app, "paste", lambda *_: pytest.fail("native failure must not fall back to paste"))
    monkeypatch.setattr(ibus, "request", lambda message, **kwargs: calls.append(message) or response)
    app.finish_dictation(process, path, "normal", SimpleNamespace(api_url="local", delay=0), 0,
                         threading.Event(), {"token": "old-field", "request_id": "one"})
    assert len(calls) == 1
    assert not path.exists()
    logs = capsys.readouterr().out
    assert "Dictation error" in logs
    assert "private speech" not in logs


def test_helper_timeout_does_not_silently_select_clipboard(monkeypatch):
    def timeout(*args):
        raise TimeoutError("helper stalled")
    monkeypatch.setattr(ibus, "request", timeout)
    with pytest.raises(TimeoutError):
        ibus.begin("auto")


def installer_module():
    path = Path(__file__).resolve().parents[1] / "install_ibus.py"
    spec = importlib.util.spec_from_file_location("install_ibus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_preserves_existing_service_and_rejects_foreign_dropin(tmp_path):
    installer = installer_module()
    config = tmp_path / "config"
    base = config / "systemd/user/phonon-dictation.service"
    base.parent.mkdir(parents=True)
    base.write_text("custom existing service\n")
    binary = tmp_path / "binary"
    binary.write_bytes(b"example binary")
    prefix = tmp_path / "prefix with spaces"
    helper, descriptor = installer.install(prefix, config, binary, True)
    assert base.read_text() == "custom existing service\n"
    assert helper.read_bytes() == binary.read_bytes()
    assert "--ibus" in descriptor.read_text()
    assert "<layout>gb</layout>" in descriptor.read_text()
    # Re-running our own installation is supported.
    installer.install(prefix, config, binary, True)
    dropin = config / f"systemd/user/{installer.IBUS_SERVICE}.d/50-phonon.conf"
    dropin.write_text("someone else's configuration\n")
    with pytest.raises(SystemExit, match="unrelated configuration"):
        installer.install(prefix, config, binary, True)


def test_component_discovery_keeps_overrides_and_xdg_components(monkeypatch, tmp_path):
    installer = installer_module()
    components = tmp_path / "share/ibus/component"
    components.mkdir(parents=True)
    monkeypatch.setenv("IBUS_COMPONENT_PATH", "/custom/one/:/custom/two:/custom/one")
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "share"))
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    def unavailable(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(installer.subprocess, "check_output", unavailable)
    assert installer.component_paths() == ["/custom/one", "/custom/two", str(components)]


def test_explicit_cargo_target_is_used_for_build_and_no_build(monkeypatch, tmp_path):
    installer = installer_module()
    monkeypatch.setenv("CARGO_TARGET_DIR", str(tmp_path / "nix-target"))
    assert installer.target_directory() == tmp_path / "nix-target"


def test_descriptor_generation_does_not_install_user_configuration(tmp_path):
    installer = installer_module()
    helper = Path("/nix/store/example/bin/phonon-ibus-helper")
    descriptor = installer.write_descriptor(helper, tmp_path / "components")
    assert str(helper) in descriptor.read_text()
    assert list(tmp_path.iterdir()) == [tmp_path / "components"]
