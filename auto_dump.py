#!/usr/bin/env python3
"""
Auto-commit TradingView CSV dumps to GitHub.
Monitors ./tv-dumps/ for new/modified .csv files and auto-pushes them.
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent


class TVDumpHandler(FileSystemEventHandler):
    """Handles .csv file creation/modification events in tv-dumps directory."""
    
    def __init__(self, repo_root: str, cooldown: float = 2.0):
        self.repo_root = Path(repo_root).resolve()
        self.cooldown = cooldown
        self._pending_files = set()
        self._processing = False
    
    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and event.src_path.endswith('.csv'):
            self._handle_file(event.src_path)
    
    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent) and event.src_path.endswith('.csv'):
            self._handle_file(event.src_path)
    
    def _handle_file(self, file_path: str):
        """Queue file for processing with cooldown to allow write completion."""
        file_path = Path(file_path).resolve()
        if file_path in self._pending_files:
            return
        
        self._pending_files.add(file_path)
        print(f"[MONITOR] Detected: {file_path.name}")
        
        # Wait for TradingView to finish writing
        time.sleep(self.cooldown)
        
        self._commit_file(file_path)
        self._pending_files.discard(file_path)
    
    def _commit_file(self, file_path: Path):
        """Run git add, commit, and push for the detected file."""
        try:
            # Change to repo root
            os.chdir(self.repo_root)
            
            # Stage the file
            result = subprocess.run(
                ['git', 'add', str(file_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"[ERROR] git add failed: {result.stderr}")
                return
            
            # Commit
            result = subprocess.run(
                ['git', 'commit', '-m', 'Auto-dump from TradingView'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                # Check if nothing to commit
                if 'nothing to commit' in result.stdout or 'nothing to commit' in result.stderr:
                    print(f"[SKIP] No changes to commit for {file_path.name}")
                    return
                print(f"[ERROR] git commit failed: {result.stderr}")
                return
            
            print(f"[COMMIT] {file_path.name}")
            
            # Push
            result = subprocess.run(
                ['git', 'push'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"[ERROR] git push failed: {result.stderr}")
                return
            
            print(f"[PUSHED] {file_path.name}")
            
        except Exception as e:
            print(f"[ERROR] {e}")


def main():
    # Get the workspace root (parent of script location)
    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir
    watch_dir = repo_root / 'tv-dumps'
    
    # Ensure tv-dumps exists
    watch_dir.mkdir(exist_ok=True)
    
    # Verify it's a git repo
    if not (repo_root / '.git').exists():
        print(f"[ERROR] Not a git repository: {repo_root}")
        sys.exit(1)
    
    print(f"[START] Monitoring: {watch_dir}")
    print(f"[REPO]  Root: {repo_root}")
    print("[CTRL+C] to stop\n")
    
    # Set up watchdog
    event_handler = TVDumpHandler(repo_root)
    observer = Observer()
    observer.schedule(event_handler, str(watch_dir), recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[STOP] Shutting down...")
        observer.stop()
    
    observer.join()


if __name__ == '__main__':
    main()
