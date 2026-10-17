"""Double-click desktop launcher: start the local service, then open the UI."""
import json
import socket
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8790"
CANDIDATE_PORTS = (8790, 8791, 8788, 8792)


def _url_for(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def health(port: int = 8790) -> bool:
    try:
        with urlopen(_url_for(port) + "/api/recipe-library/health", timeout=1) as response:
            return json.load(response).get("service") == "sonaqueen-recipe-studio"
    except Exception:
        return False


def _find_running_port() -> int | None:
    for port in CANDIDATE_PORTS:
        if health(port):
            return port
    return None


def _pick_free_port() -> int:
    for port in CANDIDATE_PORTS:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("8790 / 8791 / 8788 / 8792 連接埠皆正由其他程式使用，請關閉佔用程式後重試。")


def main():
    window = tk.Tk()
    window.title("收納王妃 · Recipe 3D 工作台")
    window.geometry("460x150")
    tk.Label(window, text="正在啟動工作台與 Blender…\n啟動後會自動開啟操作畫面。", font=("Microsoft JhengHei", 12), pady=30).pack()
    window.update()
    try:
        port = _find_running_port()
        if port is None:
            port = _pick_free_port()
            logs = ROOT / ".fox3d-work" / "recipe-studio"
            logs.mkdir(parents=True, exist_ok=True)
            executable = Path(sys.executable).with_name("python.exe") if sys.platform == "win32" else Path(sys.executable)
            with (logs / "server.log").open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [str(executable), str(ROOT / "scripts/run_recipe_admin.py"), "--port", str(port)],
                    cwd=ROOT,
                    stdout=log,
                    stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            deadline = time.monotonic() + 180
            while not health(port):
                window.update()
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("啟動未完成，請將此紀錄交給維護人員：\n" + str(logs / "server.log"))
                time.sleep(.3)
        webbrowser.open(_url_for(port) + "/admin/recipes")
    except Exception as exc:
        messagebox.showerror("工作台啟動失敗", str(exc), parent=window)
    finally:
        window.destroy()


if __name__ == "__main__":
    main()
