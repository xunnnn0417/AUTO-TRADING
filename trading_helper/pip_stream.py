"""Live video of 目前持倉 for the phone's Picture-in-Picture (display only).

The phone page used to paint the PiP video itself; iOS freezes a background
page when the phone is locked, so the floating window went black / stopped.
Here the computer renders the same 目前持倉 picture and ffmpeg turns it into a
short-segment HLS live stream. The phone only plays it, so the numbers keep
coming from the computer even while the page is frozen.

ffmpeg runs only while a phone asks for the stream and stops a minute after
the last request. Without ffmpeg nothing changes: the phone keeps its old
in-page video.
"""
from __future__ import annotations

import glob
import os
import queue
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time

WIDTH, HEIGHT, FPS = 720, 400, 2
IDLE_SECONDS = 60
LIST_SEGMENTS = 3   # tiny playlist window: nothing to rewind to (lock-screen ±15 s)
KEEP_SECONDS = 30  # old files stay on disk so a resumed player still finds them
SEGMENT = re.compile(r"(live\.m3u8|seg\d{5}\.ts)")


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    base = os.environ.get("LOCALAPPDATA", "")
    hits = glob.glob(os.path.join(base, "Microsoft", "WinGet", "Packages", "*FFmpeg*",
                                  "**", "bin", "ffmpeg.exe"), recursive=True) if base else []
    return sorted(hits)[-1] if hits else ""


class PipStream:
    """render() -> raw BGRA bytes of WIDTH x HEIGHT (called on the GUI thread)."""

    def __init__(self, render, ffmpeg: str | None = None):
        self.render = render
        self.ffmpeg = find_ffmpeg() if ffmpeg is None else ffmpeg
        self.token = secrets.token_hex(16)
        self.proc = None
        self.dir = ""
        self.frames: queue.Queue = queue.Queue(maxsize=2)
        self.last_request = 0.0
        self.writer = None

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg)

    @property
    def path(self) -> str:
        return f"/pip/live/{self.token}/live.m3u8" if self.available else ""

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def read(self, token: str, name: str) -> bytes | None:
        """Bytes of a playlist / segment for an HTTP request, or None."""
        if not self.available or token != self.token or not SEGMENT.fullmatch(name):
            return None
        self.last_request = time.monotonic()
        if not self.running:
            self.start()
        target = os.path.join(self.dir, name)
        if name == "live.m3u8":
            # First request after a start: wait briefly for the first segments.
            deadline = time.monotonic() + 4
            while not os.path.exists(target) and time.monotonic() < deadline and self.running:
                self.tick()
                time.sleep(0.1)
        try:
            with open(target, "rb") as handle:
                return handle.read()
        except OSError:
            return None

    def start(self) -> None:
        self.stop()
        self.dir = tempfile.mkdtemp(prefix="pipstream-")
        command = [
            self.ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
            # Silent audio: iOS keeps an audible video playing while the phone is
            # locked; a video-only one is paused (frozen / black PiP).
            "-re", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "32k",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
            "-g", str(FPS), "-keyint_min", str(FPS), "-sc_threshold", "0",
            "-f", "hls", "-hls_time", "1", "-hls_list_size", str(LIST_SEGMENTS), "-hls_delete_threshold", str(KEEP_SECONDS),
            "-hls_flags", "delete_segments+independent_segments+omit_endlist",
            "-hls_segment_filename", os.path.join(self.dir, "seg%05d.ts"),
            os.path.join(self.dir, "live.m3u8"),
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=flags)
        self.frames = queue.Queue(maxsize=2)
        self.writer = threading.Thread(target=self._write, args=(self.proc, self.frames), daemon=True)
        self.writer.start()

    def _write(self, proc, frames) -> None:
        while proc.poll() is None:
            frame = frames.get()
            if frame is None:
                break
            try:
                proc.stdin.write(frame)
                proc.stdin.flush()
            except (OSError, ValueError):
                break

    def tick(self) -> None:
        """Called FPS times a second on the GUI thread."""
        if not self.running:
            return
        if time.monotonic() - self.last_request > IDLE_SECONDS:
            self.stop()
            return
        frame = self.render()
        if not frame:
            return
        try:
            self.frames.put_nowait(frame)
        except queue.Full:
            try:
                self.frames.get_nowait()   # drop the oldest; live view only
            except queue.Empty:
                pass
            try:
                self.frames.put_nowait(frame)
            except queue.Full:
                pass

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                self.frames.put_nowait(None)
            except queue.Full:
                pass
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir = ""
