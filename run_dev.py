"""
run_dev.py — Development runner with auto-reload

Starts main.py and restarts the process automatically on code changes.
Usage:
    python3 run_dev.py
"""
import subprocess
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCHED_EXTENSIONS = {'.py'}
WATCHED_DIRS = ['app', 'main.py']

class RestartHandler(FileSystemEventHandler):
    def __init__(self, restart_callback):
        super().__init__()
        self.restart_callback = restart_callback

    def on_any_event(self, event):
        if event.is_directory:
            return
        if any(event.src_path.endswith(ext) for ext in WATCHED_EXTENSIONS):
            self.restart_callback()

def run_main_py():
    return subprocess.Popen([sys.executable, 'main.py'])

def main():
    process = run_main_py()
    needs_restart = False

    def restart():
        nonlocal needs_restart
        needs_restart = True
        process.terminate()

    event_handler = RestartHandler(restart)
    observer = Observer()
    for path in WATCHED_DIRS:
        observer.schedule(event_handler, str(Path(path).resolve()), recursive=True)
    observer.start()

    try:
        while True:
            if needs_restart:
                process.wait()
                process = run_main_py()
                needs_restart = False
            time.sleep(0.5)
    except KeyboardInterrupt:
        process.terminate()
    finally:
        observer.stop()
        observer.join()

if __name__ == '__main__':
    main()
