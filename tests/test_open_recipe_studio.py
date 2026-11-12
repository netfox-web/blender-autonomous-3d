"""Offline tests for the desktop Recipe Studio launcher."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest


PATH = Path(__file__).resolve().parents[1] / "scripts/open_recipe_studio.py"
spec = importlib.util.spec_from_file_location("open_recipe_studio", PATH)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    window = MagicMock()
    monkeypatch.setattr(launcher.tk, "Tk", lambda: window)
    monkeypatch.setattr(launcher.tk, "Label", MagicMock())
    browser = MagicMock()
    error = MagicMock()
    popen = MagicMock()
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    monkeypatch.setattr(launcher.messagebox, "showerror", error)
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.time, "sleep", lambda _: None)
    return window, browser, error, popen


def test_reuses_existing_service_on_actual_port(monkeypatch, desktop):
    window, browser, error, popen = desktop
    checked = []
    monkeypatch.setattr(launcher, "health", lambda port: checked.append(port) or port == 8788)
    monkeypatch.setattr(launcher, "_pick_free_port", MagicMock(side_effect=AssertionError("must reuse service")))

    launcher.main()

    assert checked == [8790, 8791, 8788]
    browser.assert_called_once_with("http://127.0.0.1:8788/admin/recipes")
    popen.assert_not_called()
    error.assert_not_called()
    window.destroy.assert_called_once()


def test_occupied_ports_start_service_on_first_free_port(monkeypatch, desktop):
    window, browser, error, popen = desktop
    binds = []
    sock = MagicMock()
    sock.__enter__.return_value = sock

    def bind(address):
        binds.append(address)
        if address[1] in (8790, 8791):
            raise OSError("occupied")

    sock.bind.side_effect = bind
    monkeypatch.setattr(launcher.socket, "socket", lambda: sock)
    health = MagicMock(side_effect=[False, False, False, False, False, True])
    monkeypatch.setattr(launcher, "health", health)
    popen.return_value.poll.return_value = None

    launcher.main()

    assert binds == [("127.0.0.1", 8790), ("127.0.0.1", 8791), ("127.0.0.1", 8788)]
    assert popen.call_args.args[0][-2:] == ["--port", "8788"]
    assert health.call_args_list[-2:] == [((8788,),), ((8788,),)]
    browser.assert_called_once_with("http://127.0.0.1:8788/admin/recipes")
    error.assert_not_called()
    window.destroy.assert_called_once()


def test_all_ports_occupied_reports_failure(monkeypatch, desktop):
    window, browser, error, popen = desktop
    monkeypatch.setattr(launcher, "health", lambda port: False)
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.bind.side_effect = OSError("occupied")
    monkeypatch.setattr(launcher.socket, "socket", lambda: sock)

    launcher.main()

    assert [call.args[0][1] for call in sock.bind.call_args_list] == list(launcher.CANDIDATE_PORTS)
    assert "皆正由其他程式使用" in error.call_args.args[1]
    browser.assert_not_called()
    popen.assert_not_called()
    window.destroy.assert_called_once()


def test_server_exit_reports_failure_without_opening_browser(monkeypatch, desktop):
    window, browser, error, popen = desktop
    monkeypatch.setattr(launcher, "_find_running_port", lambda: None)
    monkeypatch.setattr(launcher, "_pick_free_port", lambda: 8791)
    monkeypatch.setattr(launcher, "health", lambda port: False)
    popen.return_value.poll.return_value = 1

    launcher.main()

    assert "啟動未完成" in error.call_args.args[1]
    assert "server.log" in error.call_args.args[1]
    browser.assert_not_called()
    window.destroy.assert_called_once()
