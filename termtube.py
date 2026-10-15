import json

import os

import re

import sys

from datetime import datetime

from pathlib import Path



import yt_dlp

from PySide6.QtCore import QUrl, Qt, QTimer

from PySide6.QtGui import QKeySequence, QShortcut

from PySide6.QtWidgets import (

    QApplication, QMainWindow, QMessageBox, QWidget, QVBoxLayout, QHBoxLayout,

    QLabel, QPushButton, QSlider, QComboBox

)

from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from PySide6.QtMultimediaWidgets import QVideoWidget



APP_NAME = "TermTube"

DEFAULT_HEIGHT = 1080

LIBRARY_DIR = Path.home() / "Videos" / "TermTube"

INDEX_PATH = LIBRARY_DIR / "library.json"
QUEUE_PATH = LIBRARY_DIR / "queue.json"
PLAYLISTS_PATH = LIBRARY_DIR / "playlists.json"
HISTORY_PATH = LIBRARY_DIR / "history.json"





def format_time(milliseconds: int) -> str:

    seconds = max(0, milliseconds // 1000)

    hours, remainder = divmod(seconds, 3600)

    minutes, seconds = divmod(remainder, 60)

    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"





def choose_quality() -> int:

    print("\nChoose maximum download quality:")

    print("  1. 720p")

    print("  2. 1080p (recommended; best stream up to this height)")

    print("  3. 1440p (2K)")

    print("  4. 2160p (4K)")

    print("  5. Best available (may be very large)")

    choices = {"1": 720, "2": 1080, "3": 1440, "4": 2160, "5": 0}

    answer = input("Quality [2]: ").strip() or "2"

    if answer not in choices:

        print("Unknown choice; using 1080p.")

        return DEFAULT_HEIGHT

    return choices[answer]





def load_library() -> list[dict]:

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    if not INDEX_PATH.exists():

        return []

    try:

        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

        return [item for item in data if isinstance(item, dict)]

    except (OSError, json.JSONDecodeError):

        print("Warning: library index could not be read; starting with an empty index.")

        return []





def save_json_atomic(path: Path, data) -> None:
    """Write JSON via a temporary file so interruption won't corrupt saved state."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
        return value
    except (OSError, json.JSONDecodeError):
        print(f"Warning: could not read {path.name}; using an empty/default state.")
        return default


def save_library(items: list[dict]) -> None:
    save_json_atomic(INDEX_PATH, items)


def load_queue() -> list[dict]:
    data = load_json(QUEUE_PATH, [])
    return [item for item in data if isinstance(item, dict) and item.get("url")]


def save_queue(items: list[dict]) -> None:
    save_json_atomic(QUEUE_PATH, items)


def load_playlists() -> dict:
    data = load_json(PLAYLISTS_PATH, {})
    return data if isinstance(data, dict) else {}


def load_history() -> list[dict]:
    data = load_json(HISTORY_PATH, [])
    return [item for item in data if isinstance(item, dict) and item.get("path")]





def library_item_path(item: dict) -> Path | None:

    path = Path(item.get("path", ""))

    return path if path.is_file() else None





def selected_stream_stats(info: dict) -> tuple[int | None, float | None]:

    """Return selected video height and approximate stream bitrate when available."""

    requested = info.get("requested_formats") or []

    video_stream = next(

        (fmt for fmt in requested if fmt.get("vcodec") not in (None, "none")),

        None,

    )

    height = (video_stream or {}).get("height") or info.get("height")

    bitrate = (

        (video_stream or {}).get("tbr")

        or info.get("tbr")

        or (video_stream or {}).get("vbr")

    )

    try:

        height = int(height) if height else None

    except (TypeError, ValueError):

        height = None

    try:

        bitrate = float(bitrate) if bitrate else None

    except (TypeError, ValueError):

        bitrate = None

    return height, bitrate





def choose_library_item(items: list[dict]) -> dict | None:

    valid = [(i, item) for i, item in enumerate(items) if library_item_path(item)]

    if not valid:

        print("\nYour library is empty. Download a video first.")

        return None

    print("\n=== TermTube Library ===")

    for shown, (_, item) in enumerate(valid, start=1):

        title = item.get("title") or "Untitled video"

        quality = f"{item.get('height')}p" if item.get("height") else "quality unknown"

        print(f"  {shown}. {title} [{quality}]")

    answer = input("Enter number to play, or Enter to cancel: ").strip()

    if not answer:

        return None

    if not answer.isdigit() or not 1 <= int(answer) <= len(valid):

        print("Invalid selection.")

        return None

    return valid[int(answer) - 1][1]







def delete_library_item(items: list[dict]) -> list[dict]:

    """Delete a selected video file and remove its entry from the library index."""

    valid = [(i, item) for i, item in enumerate(items) if library_item_path(item)]

    if not valid:

        print("\nYour library is empty. Nothing to delete.")

        return items



    print("\n=== Delete from TermTube Library ===")

    for shown, (_, item) in enumerate(valid, start=1):

        path = library_item_path(item)

        title = item.get("title") or (path.name if path else "Untitled video")

        print(f"  {shown}. {title}")

    answer = input("Enter number to delete, or Enter to cancel: ").strip()

    if not answer:

        print("Delete cancelled.")

        return items

    if not answer.isdigit() or not 1 <= int(answer) <= len(valid):

        print("Invalid selection; nothing was deleted.")

        return items



    item_index, item = valid[int(answer) - 1]

    path = library_item_path(item)

    if path is None:

        print("The video file no longer exists; nothing was deleted.")

        return items



    # Only allow deletion of files stored inside TermTube's own library folder.

    try:

        path.resolve().relative_to(LIBRARY_DIR.resolve())

    except ValueError:

        print("Safety check failed: this file is outside the TermTube library. Nothing was deleted.")

        return items



    title = item.get("title") or path.name

    confirm = input(f"Permanently delete '{title}' and remove it from the library? Type DELETE to confirm: ").strip()

    if confirm != "DELETE":

        print("Delete cancelled; your video is unchanged.")

        return items



    try:

        path.unlink()

    except OSError as exc:

        print(f"Could not delete the video file: {exc}")

        return items



    updated_items = [entry for index, entry in enumerate(items) if index != item_index]

    try:

        save_library(updated_items)

    except OSError as exc:

        print(f"The video file was deleted, but the library index could not be saved: {exc}")

        return updated_items



    print(f"Deleted: {title}")

    return updated_items



def download_or_reuse(url: str, max_height: int, items: list[dict]) -> tuple[str, str, list[dict]]:

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    print("\nChecking video details…")

    inspect_options = {

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        "skip_download": True,

        "js_runtimes": {"deno": {}},

    }

    with yt_dlp.YoutubeDL(inspect_options) as ydl:

        info = ydl.extract_info(url, download=False)

    video_id = str(info.get("id") or "")

    title = info.get("title") or "YouTube video"

    webpage_url = info.get("webpage_url") or url



    for item in items:

        existing_path = library_item_path(item)

        if item.get("id") == video_id and existing_path:

            print(f"Already in your library: {title}")

            print("Reusing the existing download.")

            return str(existing_path), item.get("title", title), items



    # Also recover a file already present if the index was deleted or rebuilt.

    # Do not use glob with square brackets in the video ID pattern:

    # glob treats [id] as a character class rather than literal brackets.

    existing_files = [

        p for p in LIBRARY_DIR.iterdir()

        if video_id and p.is_file() and p.name.endswith(f" [{video_id}].mp4")

    ]

    if existing_files:

        path = existing_files[0]

        recovered_height, _ = selected_stream_stats(info)

        item = {

            "id": video_id, "title": title, "url": webpage_url,

            "path": str(path), "height": recovered_height,

            "added_at": datetime.now().isoformat(timespec="seconds")

        }

        items.append(item)

        save_library(items)

        print("Found an existing video file; added it to the library index.")

        return str(path), title, items



    # Don't force H.264/MP4 first: that can choose a lower-bitrate stream

    # when YouTube offers a better VP9/AV1 stream at the same resolution.

    # Prefer yt-dlp's best separate video+audio streams within the chosen cap.

    if max_height == 0:

        format_selector = "bestvideo+bestaudio/best"

    else:

        format_selector = (

            f"bestvideo[height<={max_height}]+bestaudio/"

            f"best[height<={max_height}]/best"

        )



    output_template = str(LIBRARY_DIR / "%(title).150B [%(id)s].%(ext)s")

    last_percent = None



    def progress_hook(data):

        nonlocal last_percent

        if data.get("status") != "downloading":

            return

        total = data.get("total_bytes") or data.get("total_bytes_estimate")

        downloaded = data.get("downloaded_bytes", 0)

        speed = data.get("speed")

        eta = data.get("eta")

        if total:

            percent = downloaded / total * 100

            rounded = int(percent)

            if rounded != last_percent:

                last_percent = rounded

                width = 24

                filled = int(width * percent / 100)

                bar = "#" * filled + "-" * (width - filled)

                speed_text = f"{speed * 8 / 1_000_000:.1f} Mbps ({speed / 1024 / 1024:.1f} MiB/s)" if speed else "calculating"

                eta_text = f" ETA {eta}s" if eta is not None else ""

                print(f"\rDownloading [{bar}] {percent:5.1f}%  {speed_text}{eta_text}   ", end="", flush=True)

        else:

            print("\rDownloading…", end="", flush=True)



    options = {

        "format": format_selector,

        "merge_output_format": "mp4",

        "outtmpl": output_template,

        "noplaylist": True,

        "progress_hooks": [progress_hook],

        "js_runtimes": {"deno": {}},

        "quiet": True,

        "no_warnings": True,

        "continuedl": True,

        "retries": 10,

        "fragment_retries": 10,

        "file_access_retries": 3,

        "socket_timeout": 30,

    }

    with yt_dlp.YoutubeDL(options) as ydl:

        downloaded_info = ydl.extract_info(url, download=True)



    selected_height, selected_bitrate = selected_stream_stats(downloaded_info)

    print("\nDownload complete. Saving to your library…")

    if selected_height:

        print(f"Selected video stream: {selected_height}p")

    if selected_bitrate:

        print(f"Reported stream bitrate: approximately {selected_bitrate:.0f} kb/s")

    else:

        print("Reported stream bitrate: unavailable from YouTube metadata")

    video_id = str(downloaded_info.get("id") or video_id)

    # Match the literal "[video_id]" suffix using string checks, not glob syntax.

    candidates = [

        p for p in LIBRARY_DIR.iterdir()

        if p.is_file()

        and video_id

        and p.name.endswith(f" [{video_id}].{p.suffix.lstrip('.')}")

        and not p.name.endswith((".part", ".ytdl", ".temp"))

        and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}

    ]

    if not candidates:

        raise RuntimeError(f"Download completed, but no playable file was found in {LIBRARY_DIR}")

    candidates.sort(key=lambda p: (p.suffix.lower() != ".mp4", -p.stat().st_size))

    path = candidates[0]

    item = {

        "id": video_id,

        "title": downloaded_info.get("title") or title,

        "url": downloaded_info.get("webpage_url") or webpage_url,

        "path": str(path),

        "height": selected_height or downloaded_info.get("height"),

        "bitrate_kbps": selected_bitrate,

        "added_at": datetime.now().isoformat(timespec="seconds"),

    }

    items = [old for old in items if old.get("id") != video_id]

    items.append(item)

    save_library(items)

    print(f"Saved: {path}")

    return str(path), item["title"], items



def expand_youtube_playlist(url: str) -> list[dict]:
    """Expand a YouTube playlist URL into individual video queue entries.

    A normal video URL returns a single entry. Playlist metadata is extracted
    without downloading media; actual downloads still happen when the queue is played.
    """
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
        "js_runtimes": {"deno": {}},
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info.get("entries") if isinstance(info, dict) else None
    if not entries:
        title = info.get("title", url) if isinstance(info, dict) else url
        return [{"url": url, "title": title}]

    expanded = []
    for entry in entries:
        if not entry:
            continue
        video_url = entry.get("webpage_url") or entry.get("url")
        video_id = entry.get("id")
        if not video_url or not str(video_url).startswith(("http://", "https://")):
            if video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                continue
        expanded.append({"url": video_url, "title": entry.get("title") or str(video_id or video_url)})
    return expanded


def manage_queue(items: list[dict]) -> tuple[bool, list[dict]]:
    """Interactive queue and named-playlist manager. Returns (play_requested, queue)."""
    queue = load_queue()
    playlists = load_playlists()

    while True:
        print("\n=== TermTube Queue & Playlists ===")
        if queue:
            for i, entry in enumerate(queue, 1):
                print(f"  {i}. {entry.get('title') or entry.get('url')}")
        else:
            print("  Queue is empty.")
        print("\nA. Add YouTube URL")
        print("R. Remove queue item")
        print("U. Move item up")
        print("D. Move item down")
        print("S. Save queue as playlist")
        print("L. Load playlist")
        print("E. Delete saved playlist")
        print("P. Play queue")
        print("C. Clear queue")
        print("B. Back")
        choice = input("Choose an action: ").strip().lower()

        if choice == "a":
            url = input("Paste YouTube video or playlist URL: ").strip()
            if not url.startswith(("https://", "http://")):
                print("Please enter a valid http(s) URL.")
                continue
            try:
                print("Checking URL / expanding playlist…")
                new_entries = expand_youtube_playlist(url)
                if not new_entries:
                    print("No available videos were found in that URL.")
                    continue
                queue.extend(new_entries)
                save_queue(queue)
                if len(new_entries) == 1:
                    print(f"Added: {new_entries[0].get('title')}. It will download when you start the queue.")
                else:
                    print(f"Added {len(new_entries)} playlist videos to the queue. They will download when you start the queue.")
            except Exception as exc:
                print(f"Could not read that YouTube URL: {exc}")
        elif choice == "r":
            if not queue:
                print("Queue is empty.")
                continue
            answer = input("Queue number to remove: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(queue):
                removed = queue.pop(int(answer) - 1)
                save_queue(queue)
                print(f"Removed: {removed.get('title') or removed.get('url')}")
            else:
                print("Invalid queue number.")
        elif choice in ("u", "d"):
            if not queue:
                print("Queue is empty.")
                continue
            answer = input("Queue number to move: ").strip()
            if not answer.isdigit() or not 1 <= int(answer) <= len(queue):
                print("Invalid queue number.")
                continue
            old = int(answer) - 1
            new = old - 1 if choice == "u" else old + 1
            if 0 <= new < len(queue):
                queue[old], queue[new] = queue[new], queue[old]
                save_queue(queue)
            else:
                print("That item is already at the end of that direction.")
        elif choice == "s":
            if not queue:
                print("Add at least one video before saving a playlist.")
                continue
            name = input("Playlist name: ").strip()
            if not name:
                print("Playlist name cannot be empty.")
                continue
            playlists[name] = list(queue)
            save_json_atomic(PLAYLISTS_PATH, playlists)
            print(f"Saved playlist '{name}'.")
        elif choice == "l":
            if not playlists:
                print("No saved playlists yet.")
                continue
            names = list(playlists)
            print("\nSaved playlists:")
            for i, name in enumerate(names, 1):
                print(f"  {i}. {name} ({len(playlists[name])} videos)")
            answer = input("Playlist number to load, or Enter to cancel: ").strip()
            if not answer:
                continue
            if answer.isdigit() and 1 <= int(answer) <= len(names):
                name = names[int(answer) - 1]
                mode = input("Replace queue or append? [R/a]: ").strip().lower() or "r"
                if mode == "a":
                    queue.extend(playlists[name])
                else:
                    queue = list(playlists[name])
                save_queue(queue)
                print(f"Loaded '{name}'.")
            else:
                print("Invalid playlist number.")
        elif choice == "e":
            if not playlists:
                print("No saved playlists to delete.")
                continue
            names = list(playlists)
            print("\nSaved playlists:")
            for i, name in enumerate(names, 1):
                print(f"  {i}. {name} ({len(playlists[name])} videos)")
            answer = input("Playlist number to delete, or Enter to cancel: ").strip()
            if not answer:
                continue
            if answer.isdigit() and 1 <= int(answer) <= len(names):
                name = names[int(answer) - 1]
                confirm = input(f"Delete playlist '{name}'? Type DELETE to confirm: ").strip()
                if confirm == "DELETE":
                    del playlists[name]
                    save_json_atomic(PLAYLISTS_PATH, playlists)
                    print(f"Deleted playlist '{name}'. Videos in your library are not deleted.")
                else:
                    print("Deletion cancelled.")
            else:
                print("Invalid playlist number.")
        elif choice == "p":
            if not queue:
                print("Queue is empty.")
                continue
            save_queue(queue)
            return True, list(queue)
        elif choice == "c":
            confirm = input("Clear the entire queue? Type CLEAR to confirm: ").strip()
            if confirm == "CLEAR":
                queue.clear()
                save_queue(queue)
                print("Queue cleared.")
        elif choice == "b":
            save_queue(queue)
            return False, queue
        else:
            print("Unknown choice.")


def show_history_and_select() -> dict | None:
    history = load_history()
    existing = [entry for entry in history if Path(entry.get("path", "")).is_file()]
    if not existing:
        print("\nNo watch history yet.")
        return None
    print("\n=== TermTube Watch History ===")
    for i, entry in enumerate(existing, 1):
        watched = entry.get("last_watched", "unknown time")
        position = format_time(int(entry.get("position_ms") or 0))
        print(f"  {i}. {entry.get('title') or Path(entry['path']).stem} — resume at {position} (last watched {watched})")
    answer = input("Enter number to resume, or Enter to cancel: ").strip()
    if not answer:
        return None
    if not answer.isdigit() or not 1 <= int(answer) <= len(existing):
        print("Invalid selection.")
        return None
    return existing[int(answer) - 1]


def download_queue(queue: list[dict], items: list[dict], max_height: int) -> tuple[list[dict], list[dict]]:
    """Download queued URLs one by one, preserving successful downloads if one fails."""
    playable = []
    for index, entry in enumerate(queue, 1):
        url = entry.get("url", "")
        print(f"\nQueue item {index}/{len(queue)}")
        try:
            path, title, items = download_or_reuse(url, max_height, items)
            playable.append({"path": path, "title": title})
        except KeyboardInterrupt:
            print("\nQueue download cancelled. Successfully downloaded items are kept.")
            break
        except Exception as exc:
            print(f"Could not prepare this queue item: {exc}")
            retry = input("Continue with the remaining queue items? [Y/n]: ").strip().lower()
            if retry == "n":
                break
    return playable, items


class VideoWindow(QMainWindow):

    def __init__(
        self,
        video_path: str,
        title: str,
        playback_items: list[dict] | None = None,
        resume_position: int = 0,
    ):
        super().__init__()
        self.playback_items = playback_items or [{"path": video_path, "title": title}]
        self.current_index = next(
            (i for i, entry in enumerate(self.playback_items) if str(entry.get("path")) == str(video_path)),
            0,
        )
        self.current_path = str(video_path)
        self.current_title = title
        self._pending_resume_position = max(0, int(resume_position or 0))
        # Do not save the initial 0 ms position over saved history before Qt has
        # loaded the media and applied the requested resume seek.
        self._resume_applied = self._pending_resume_position <= 0
        self._awaiting_resume_position = False
        self._resume_target_position = 0
        self._resume_seek_attempts = 0
        self._resume_seek_scheduled = False
        self._last_saved_position = -10_000
        self.setWindowTitle(f"{APP_NAME} — {title}")

        self.resize(1180, 760)

        self.setMinimumSize(720, 480)

        self._is_seeking = False



        self.audio = QAudioOutput()

        self.audio.setVolume(0.7)

        self.player = QMediaPlayer(self)

        self.player.setAudioOutput(self.audio)

        self.video_widget = QVideoWidget(self)

        self.video_widget.setMinimumSize(640, 360)

        self.player.setVideoOutput(self.video_widget)



        self.time_label = QLabel("00:00 / 00:00")

        self.time_label.setMinimumWidth(190)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)

        self.seek_slider.setRange(0, 0)

        self.seek_slider.sliderPressed.connect(lambda: setattr(self, "_is_seeking", True))

        self.seek_slider.sliderReleased.connect(self._seek_finished)



        self.play_button = QPushButton("Pause")

        self.play_button.clicked.connect(self.toggle_play_pause)

        self.back_button = QPushButton("−10s")

        self.back_button.clicked.connect(lambda: self.seek_by(-10_000))

        self.forward_button = QPushButton("+10s")

        self.forward_button.clicked.connect(lambda: self.seek_by(10_000))

        self.volume_label = QLabel("Volume 70%")

        self.speed_combo = QComboBox()

        self.speed_combo.addItems(["0.5×", "0.75×", "1.0×", "1.25×", "1.5×", "1.75×", "2.0×"])

        self.speed_combo.setCurrentText("1.0×")

        self.speed_combo.currentTextChanged.connect(self.set_speed)



        time_row = QHBoxLayout()

        time_row.addWidget(self.time_label)

        time_row.addWidget(self.seek_slider, 1)

        controls = QHBoxLayout()

        controls.addWidget(self.play_button)

        controls.addWidget(self.back_button)

        controls.addWidget(self.forward_button)

        controls.addStretch(1)

        controls.addWidget(QLabel("Speed"))

        controls.addWidget(self.speed_combo)

        controls.addWidget(self.volume_label)



        central = QWidget()

        layout = QVBoxLayout(central)

        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(self.video_widget, 1)

        layout.addLayout(time_row)

        layout.addLayout(controls)

        self.setCentralWidget(central)

        self.statusBar().showMessage(

            "Space play/pause | ←/→ seek 10s | Shift+←/→ seek 5s | ↑/↓ volume | "

            "M mute | F fullscreen | Esc exit fullscreen | Q quit"

        )



        for key, callback in [

            ("Space", self.toggle_play_pause),

            ("Left", lambda: self.seek_by(-10_000)),

            ("Right", lambda: self.seek_by(10_000)),

            ("Shift+Left", lambda: self.seek_by(-5_000)),

            ("Shift+Right", lambda: self.seek_by(5_000)),

            ("Up", lambda: self.change_volume(0.05)),

            ("Down", lambda: self.change_volume(-0.05)),

            ("M", self.toggle_mute),

            ("F", self.toggle_fullscreen),

            ("Escape", self.leave_fullscreen),

            ("Q", self.close),

        ]:

            shortcut = QShortcut(QKeySequence(key), self)

            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)

            shortcut.activated.connect(callback)



        self.player.positionChanged.connect(self.update_position)

        self.player.durationChanged.connect(self.update_duration)

        self.player.playbackStateChanged.connect(self.update_play_button)

        self.player.errorOccurred.connect(self.show_player_error)
        self.player.mediaStatusChanged.connect(self.handle_media_status)
        self.player.setSource(QUrl.fromLocalFile(video_path))



    def _seek_finished(self):

        self.player.setPosition(self.seek_slider.value())

        self._is_seeking = False



    def toggle_play_pause(self):

        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:

            self.player.pause()

        else:

            self.player.play()



    def update_play_button(self, state):

        self.play_button.setText("Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play")



    def seek_by(self, amount_ms):

        target = max(0, self.player.position() + amount_ms)

        if self.player.duration() > 0:

            target = min(target, self.player.duration())

        self.player.setPosition(target)



    def change_volume(self, amount):

        value = max(0.0, min(1.0, self.audio.volume() + amount))

        self.audio.setVolume(value)

        self.volume_label.setText(f"Volume {round(value * 100)}%")

        self.statusBar().showMessage(f"Volume: {round(value * 100)}%", 1500)



    def toggle_mute(self):

        self.audio.setMuted(not self.audio.isMuted())

        self.statusBar().showMessage("Muted" if self.audio.isMuted() else "Unmuted", 1500)



    def set_speed(self, text):

        try:

            self.player.setPlaybackRate(float(text.replace("×", "")))

        except ValueError:

            pass



    def toggle_fullscreen(self):

        self.showNormal() if self.isFullScreen() else self.showFullScreen()



    def leave_fullscreen(self):

        if self.isFullScreen():

            self.showNormal()



    def update_position(self, position):
        if not self._is_seeking:
            self.seek_slider.setValue(position)
        self.time_label.setText(f"{format_time(position)} / {format_time(self.player.duration())}")

        # Ignore stale 0 ms updates that Qt can emit immediately after setPosition.
        # Only start saving again once the player reports a position near the target.
        if self._awaiting_resume_position:
            if abs(position - self._resume_target_position) <= 3_000:
                self._awaiting_resume_position = False
                self._resume_applied = True
                self._pending_resume_position = 0
                self._last_saved_position = int(position)
            else:
                return

        if self._resume_applied and abs(position - self._last_saved_position) >= 10_000:
            self.save_watch_progress(position)

    def save_watch_progress(self, position: int | None = None):
        if position is None:
            position = self.player.position()
        duration = self.player.duration()
        history = load_history()
        now = datetime.now().isoformat(timespec="seconds")
        entry = {
            "path": self.current_path,
            "title": self.current_title,
            "position_ms": max(0, int(position)),
            "last_watched": now,
        }
        # A video at its end is treated as completed, so next time starts at zero.
        if duration > 0 and position >= duration - 15_000:
            entry["position_ms"] = 0
        history = [old for old in history if str(old.get("path")) != self.current_path]
        history.insert(0, entry)
        save_json_atomic(HISTORY_PATH, history[:100])
        self._last_saved_position = int(position)

    def handle_media_status(self, status):
        # Qt can emit positionChanged(0) before the media is ready. Wait until
        # the media is loaded before seeking, otherwise the resume position may
        # be ignored and the initial zero can overwrite history.
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._apply_pending_resume()
            return

        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        self._resume_applied = True
        self._awaiting_resume_position = False
        self.save_watch_progress(self.player.duration())
        next_index = self.current_index + 1
        if next_index >= len(self.playback_items):
            self.close()
            return
        self.current_index = next_index
        entry = self.playback_items[self.current_index]
        self.current_path = str(entry["path"])
        self.current_title = entry.get("title") or Path(self.current_path).stem
        self.setWindowTitle(f"{APP_NAME} — {self.current_title}")
        history = load_history()
        saved = next((h for h in history if str(h.get("path")) == self.current_path), {})
        self._pending_resume_position = max(0, int(saved.get("position_ms") or 0))
        self._resume_applied = self._pending_resume_position <= 0
        self._awaiting_resume_position = False
        self._resume_target_position = 0
        self._resume_seek_attempts = 0
        self._resume_seek_scheduled = False
        self._last_saved_position = -10_000
        self.player.setSource(QUrl.fromLocalFile(self.current_path))
        self.player.play()
        self._apply_pending_resume()

    def _apply_pending_resume(self):
        """Schedule a resume seek; Qt may ignore setPosition until playback is active."""
        if self._resume_applied or self._pending_resume_position <= 0:
            return
        if self.player.duration() <= 0 or self._resume_seek_scheduled:
            return
        self._resume_target_position = min(
            self._pending_resume_position,
            max(0, self.player.duration() - 1_000),
        )
        self._awaiting_resume_position = True
        self._resume_applied = False
        self._resume_seek_scheduled = True
        self.statusBar().showMessage(
            f"Seeking to saved position {format_time(self._resume_target_position)}…",
            3000,
        )
        # Let Qt's multimedia backend finish opening/starting the local file.
        QTimer.singleShot(300, self._attempt_resume_seek)

    def _attempt_resume_seek(self):
        self._resume_seek_scheduled = False
        if self._resume_applied or self._pending_resume_position <= 0:
            return
        if self.player.duration() <= 0:
            return

        target = min(self._pending_resume_position, max(0, self.player.duration() - 1_000))
        self._resume_target_position = target
        self._awaiting_resume_position = True
        self.player.setPosition(target)
        QTimer.singleShot(500, self._verify_resume_seek)

    def _verify_resume_seek(self):
        if self._resume_applied or self._pending_resume_position <= 0:
            return
        current = int(self.player.position())
        target = int(self._resume_target_position)
        if abs(current - target) <= 3_000:
            self._pending_resume_position = 0
            self._awaiting_resume_position = False
            self._resume_applied = True
            self._last_saved_position = current
            self.statusBar().showMessage(f"Resumed from {format_time(current)}", 3000)
            return

        self._resume_seek_attempts += 1
        if self._resume_seek_attempts >= 8:
            self._awaiting_resume_position = False
            self.statusBar().showMessage(
                "Could not seek to saved position; playback started from the beginning.",
                6000,
            )
            # Preserve the stored timestamp rather than overwriting it with zero.
            return
        self._apply_pending_resume()

    def update_duration(self, duration):
        self.seek_slider.setRange(0, max(0, duration))
        self._apply_pending_resume()
        self.update_position(self.player.position())



    def show_player_error(self, error, error_string):

        if error != QMediaPlayer.Error.NoError:

            QMessageBox.warning(self, "TermTube playback error", error_string or str(error))



    def start_playback(self):
        self.show()
        # Start playback, but do not immediately save position 0: that could
        # overwrite the stored resume point before the media is ready.
        self.player.play()
        self._apply_pending_resume()

    def closeEvent(self, event):
        if self._resume_applied:
            self.save_watch_progress(self.player.position())
        self.player.stop()
        event.accept()





def get_resume_position(path: str) -> int:
    entry = next((h for h in load_history() if str(h.get("path")) == str(path)), {})
    return max(0, int(entry.get("position_ms") or 0))


def ask_resume(path: str, title: str) -> int:
    position = get_resume_position(path)
    if position <= 0:
        return 0
    answer = input(f"Resume '{title}' from {format_time(position)}? [Y/n]: ").strip().lower()
    return position if answer in ("", "y", "yes") else 0


def legacy_main():
    print("\n=== TermTube ===\nTerminal-first YouTube player — persistent library\n")
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    items = load_library()
    print(f"Library folder: {LIBRARY_DIR}")
    print("\n1. Download and play a YouTube URL")
    print("2. Play a video from your library")
    print("3. Manage playback queue and playlists")
    print("4. Watch history / resume")
    print("5. Delete a video from your library")
    print("6. Show library folder")
    print("7. Exit")
    choice = input("Choose [1]: ").strip() or "1"

    if choice == "7":
        return
    if choice == "6":
        print(f"\nOpen this folder in File Explorer:\n{LIBRARY_DIR}")
        try:
            os.startfile(str(LIBRARY_DIR))
        except (AttributeError, OSError):
            pass
        return
    if choice == "5":
        delete_library_item(items)
        return

    playback_items = None
    resume_position = 0
    path = None
    title = None

    if choice == "3":
        should_play, queue = manage_queue(items)
        if not should_play:
            return
        max_height = choose_quality()
        quality_text = "best available" if max_height == 0 else f"up to {max_height}p"
        print(f"\nPreparing queue ({quality_text})…")
        playback_items, items = download_queue(queue, items, max_height)
        if not playback_items:
            print("No queue items were ready to play.")
            return
        path = playback_items[0]["path"]
        title = playback_items[0]["title"]
        resume_position = get_resume_position(path)
    elif choice == "4":
        entry = show_history_and_select()
        if not entry:
            return
        path = entry["path"]
        title = entry.get("title") or Path(path).stem
        resume_position = max(0, int(entry.get("position_ms") or 0))
    elif choice == "2":
        item = choose_library_item(items)
        if not item:
            return
        path_obj = library_item_path(item)
        if path_obj is None:
            print("That video file is no longer available.")
            return
        path = str(path_obj)
        title = item.get("title") or Path(path).stem
        resume_position = ask_resume(path, title)
    elif choice == "1":
        url = sys.argv[1].strip() if len(sys.argv) > 1 else input("\nPaste YouTube URL: ").strip()
        if not url.startswith(("https://", "http://")):
            print("Please enter a valid http(s) URL.")
            raise SystemExit(2)
        max_height = choose_quality()
        quality_text = "best available" if max_height == 0 else f"up to {max_height}p"
        print(f"\nDownloading ({quality_text})…\n")
        path, title, items = download_or_reuse(url, max_height, items)
        resume_position = ask_resume(path, title)
    else:
        print("Unknown choice.")
        return

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    try:
        print(f"\nReady: {title}")
        if playback_items and len(playback_items) > 1:
            print(f"Queue contains {len(playback_items)} videos; the next one will play automatically.")
        print("Keyboard controls: Space play/pause | ←/→ seek 10s | Shift+←/→ seek 5s")
        print("                  ↑/↓ volume | M mute | F fullscreen | Esc exit fullscreen | Q quit\n")
        window = VideoWindow(
            str(path),
            title,
            playback_items=playback_items,
            resume_position=resume_position,
        )
        window.start_playback()
        app.exec()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as exc:
        print(f"\nTermTube error: {exc}", file=sys.stderr)
        print("\nCheck your connection, yt-dlp/Deno setup, and FFmpeg installation.", file=sys.stderr)
        raise SystemExit(1)
    finally:
        app.quit()




# ---------------------------------------------------------------------------
# Keyboard-first Textual dashboard
# ---------------------------------------------------------------------------

def launch_player_process(playback_items: list[dict]) -> None:
    """Launch the existing Qt video player in a separate process."""
    valid = [
        {"path": str(entry["path"]), "title": entry.get("title") or Path(entry["path"]).stem}
        for entry in playback_items
        if entry.get("path") and Path(entry["path"]).is_file()
    ]
    if not valid:
        raise RuntimeError("No playable local videos were found.")

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    queue_file = LIBRARY_DIR / "active_playback_queue.json"
    save_json_atomic(queue_file, valid)
    script_path = str(Path(__file__).resolve())
    import subprocess
    subprocess.Popen([sys.executable, script_path, "--play-queue", str(queue_file)])


def run_qt_player_from_args(queue_file: str) -> None:
    """Entry point used by the dashboard to run Qt outside Textual's event loop."""
    entries = load_json(Path(queue_file), [])
    entries = [
        {"path": str(entry.get("path", "")), "title": entry.get("title") or Path(str(entry.get("path", ""))).stem}
        for entry in entries
        if isinstance(entry, dict) and Path(str(entry.get("path", ""))).is_file()
    ]
    if not entries:
        print("No playable videos were found in the playback queue.", file=sys.stderr)
        raise SystemExit(2)

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    first = entries[0]
    window = VideoWindow(first["path"], first["title"], playback_items=entries, resume_position=0)
    window.start_playback()
    app.exec()
    app.quit()


def launch_dashboard() -> None:
    try:
        from textual import work
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Horizontal, Vertical
        from textual.widgets import DataTable, Footer, Header, Input, Static
    except ImportError:
        print(
            "TermTube's new terminal dashboard needs Textual.\n"
            "Install it with:\n\n"
            "  python -m pip install textual\n\n"
            "Then run: python termtube.py",
            file=sys.stderr,
        )
        raise SystemExit(1)

    class TermTubeApp(App):
        TITLE = "TermTube"
        SUB_TITLE = "Your video space"
        CSS = """
        Screen {
            background: #101114;
            color: #e5e7eb;
        }
        #brand {
            height: 3;
            padding: 1 2;
            background: #191a20;
            color: #f5f5f5;
            text-style: bold;
        }
        #search {
            margin: 1 2 0 2;
            border: round #393a40;
        }
        #dashboard {
            height: 1fr;
            padding: 1 2;
        }
        .panel-row {
            height: 1fr;
            min-height: 8;
        }
        .panel {
            width: 1fr;
            height: 1fr;
            border: round #393a40;
            margin: 0 1 1 0;
            padding: 0 1;
        }
        .panel-title {
            height: 1;
            color: #a1a1aa;
            text-style: bold;
            padding: 0 1;
        }
        DataTable {
            height: 1fr;
            background: #101114;
            border: none;
        }
        DataTable:focus {
            border: round #777b87;
        }
        #status {
            height: 2;
            padding: 0 2;
            color: #d4d4d8;
            background: #191a20;
        }
        #command {
            margin: 0 2 1 2;
            display: none;
        }
        Footer {
            background: #191a20;
        }
        """
        BINDINGS = [
            Binding("/", "search", "Search", show=True),
            Binding("a", "add_url", "Add URL", show=True),
            Binding("n", "save_playlist", "Save playlist", show=True),
            Binding("l", "load_playlist", "Load playlist", show=True),
            Binding("x", "delete_selected", "Delete", show=True),
            Binding("r", "remove_queue", "Remove queue item", show=False),
            Binding("ctrl+up", "move_queue_up", "Move up", show=False),
            Binding("ctrl+down", "move_queue_down", "Move down", show=False),
            Binding("q", "focus_queue", "Queue", show=True),
            Binding("h", "focus_history", "History", show=True),
            Binding("escape", "cancel_input", "Back", show=False),
            Binding("question_mark", "help", "Help", show=True),
            Binding("ctrl+o", "open_library_folder", "Open folder", show=False),
        ]

        def __init__(self):
            super().__init__()
            self.input_mode = ""
            self.library_items = []
            self.visible_library_items = []
            self.history_items = []
            self.playlists = {}
            self.queue_items = []
            self._busy = False

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("▶  TERMTUBE     YOUR VIDEO SPACE", id="brand")
            yield Input(placeholder="Search your videos…  Press / to search, A to add a YouTube URL", id="search")
            with Vertical(id="dashboard"):
                with Horizontal(classes="panel-row"):
                    with Vertical(classes="panel"):
                        yield Static("YOUR LIBRARY", classes="panel-title")
                        yield DataTable(id="library", cursor_type="row", zebra_stripes=True)
                    with Vertical(classes="panel"):
                        yield Static("RECENTLY PLAYED", classes="panel-title")
                        yield DataTable(id="history", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="panel-row"):
                    with Vertical(classes="panel"):
                        yield Static("YOUR PLAYLISTS", classes="panel-title")
                        yield DataTable(id="playlists", cursor_type="row", zebra_stripes=True)
                    with Vertical(classes="panel"):
                        yield Static("UP NEXT  ·  QUEUE", classes="panel-title")
                        yield DataTable(id="queue", cursor_type="row", zebra_stripes=True)
            yield Input(placeholder="Enter URL / playlist name / DELETE to confirm…", id="command")
            yield Static("Ready · Enter plays the focused panel · A add URL · / search · N save queue as playlist", id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#library", DataTable).add_columns("Video", "Quality")
            self.query_one("#history", DataTable).add_columns("Video", "Position")
            self.query_one("#playlists", DataTable).add_columns("Playlist", "Videos")
            self.query_one("#queue", DataTable).add_columns("Video", "Source")
            self.refresh_dashboard()
            self.query_one("#library", DataTable).focus()

        def set_status(self, message: str) -> None:
            self.query_one("#status", Static).update(message)

        def refresh_dashboard(self) -> None:
            self.library_items = [
                item for item in load_library()
                if library_item_path(item) is not None
            ]
            self.history_items = [
                entry for entry in load_history()
                if Path(entry.get("path", "")).is_file()
            ]
            self.playlists = load_playlists()
            self.queue_items = load_queue()

            search_text = self.query_one("#search", Input).value.strip().casefold()
            self.visible_library_items = [
                item for item in self.library_items
                if search_text in (item.get("title") or Path(item["path"]).stem).casefold()
            ]

            library_table = self.query_one("#library", DataTable)
            library_table.clear()
            for item in self.visible_library_items:
                title = item.get("title") or Path(item["path"]).stem
                quality = f"{item.get('height')}p" if item.get("height") else "—"
                library_table.add_row(title, quality, key=str(item["path"]))

            history_table = self.query_one("#history", DataTable)
            history_table.clear()
            for entry in self.history_items[:30]:
                title = entry.get("title") or Path(entry["path"]).stem
                position = format_time(int(entry.get("position_ms") or 0))
                history_table.add_row(title, position, key=str(entry["path"]))

            playlist_table = self.query_one("#playlists", DataTable)
            playlist_table.clear()
            for name, entries in self.playlists.items():
                playlist_table.add_row(name, str(len(entries)), key=name)

            queue_table = self.query_one("#queue", DataTable)
            queue_table.clear()
            for i, entry in enumerate(self.queue_items):
                queue_table.add_row(
                    entry.get("title") or entry.get("url") or "Untitled",
                    "YouTube URL",
                    key=str(i),
                )

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "search":
                self.refresh_dashboard()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id != "command":
                return
            value = event.value.strip()
            mode = self.input_mode
            self.input_mode = ""
            event.input.value = ""
            event.input.display = False
            if not value:
                self.set_status("Cancelled.")
                return
            if mode == "add_url":
                if not value.startswith(("https://", "http://")):
                    self.set_status("Please paste a valid http(s) URL.")
                    return
                self.add_url_worker(value)
            elif mode == "save_playlist":
                self.save_playlist_named(value)
            elif mode == "delete_playlist":
                if value != "DELETE":
                    self.set_status("Deletion cancelled. Type DELETE to confirm.")
                    return
                self.delete_selected_playlist()
            elif mode == "delete_video":
                if value != "DELETE":
                    self.set_status("Deletion cancelled. Type DELETE to confirm.")
                    return
                self.delete_selected_video()
            elif mode == "search":
                self.query_one("#search", Input).value = value
                self.query_one("#library", DataTable).focus()
                self.refresh_dashboard()

        def prompt(self, mode: str, placeholder: str) -> None:
            self.input_mode = mode
            field = self.query_one("#command", Input)
            field.placeholder = placeholder
            field.display = True
            field.value = ""
            field.focus()
            self.set_status(placeholder)

        def focused_panel(self) -> str:
            focused = self.focused
            return focused.id if focused and focused.id in {"library", "history", "playlists", "queue"} else "library"

        def selected_row(self, table_id: str):
            table = self.query_one(f"#{table_id}", DataTable)
            if table.row_count == 0:
                return None
            row_index = max(0, min(table.cursor_row, table.row_count - 1))
            return table.get_row_at(row_index)

        def action_search(self) -> None:
            field = self.query_one("#search", Input)
            field.focus()
            field.placeholder = "Type to filter your local library…"

        def action_add_url(self) -> None:
            self.prompt("add_url", "Paste a YouTube video or playlist URL and press Enter")

        def action_save_playlist(self) -> None:
            if not load_queue():
                self.set_status("Your queue is empty. Add a YouTube URL first (A).")
                return
            self.prompt("save_playlist", "Name this playlist and press Enter")

        def action_load_playlist(self) -> None:
            table = self.query_one("#playlists", DataTable)
            if table.row_count == 0:
                self.set_status("No saved playlists yet.")
                return
            row = self.selected_row("playlists")
            if row is None:
                return
            name = str(row[0])
            playlists = load_playlists()
            if name not in playlists:
                self.set_status("That playlist could not be found.")
                return
            save_queue(list(playlists[name]))
            self.refresh_dashboard()
            self.query_one("#queue", DataTable).focus()
            self.set_status(f"Loaded “{name}” into the queue. Press Enter in the queue panel to play.")

        def action_delete_selected(self) -> None:
            panel = self.focused_panel()
            if panel == "playlists":
                if self.selected_row("playlists") is None:
                    self.set_status("Select a playlist first.")
                    return
                self.prompt("delete_playlist", "Type DELETE to remove the selected playlist, then press Enter")
            elif panel == "library":
                if self.selected_row("library") is None:
                    self.set_status("Select a video first.")
                    return
                self.prompt("delete_video", "Type DELETE to remove the selected video and its file, then press Enter")
            elif panel == "queue":
                self.action_remove_queue()
            else:
                self.set_status("Focus Playlists to delete a playlist, Library to delete a video, or Queue to remove an item.")

        def action_remove_queue(self) -> None:
            table = self.query_one("#queue", DataTable)
            if table.row_count == 0:
                self.set_status("Queue is empty.")
                return
            index = max(0, min(table.cursor_row, table.row_count - 1))
            queue = load_queue()
            if index < len(queue):
                removed = queue.pop(index)
                save_queue(queue)
                self.refresh_dashboard()
                self.set_status(f"Removed “{removed.get('title') or removed.get('url')}” from the queue.")

        def action_move_queue_up(self) -> None:
            self.move_queue(-1)

        def action_move_queue_down(self) -> None:
            self.move_queue(1)

        def move_queue(self, direction: int) -> None:
            table = self.query_one("#queue", DataTable)
            queue = load_queue()
            if not queue:
                self.set_status("Queue is empty.")
                return
            old = max(0, min(table.cursor_row, len(queue) - 1))
            new = old + direction
            if not 0 <= new < len(queue):
                self.set_status("That queue item is already at the edge.")
                return
            queue[old], queue[new] = queue[new], queue[old]
            save_queue(queue)
            self.refresh_dashboard()
            table.move_cursor(row=new)
            table.focus()
            self.set_status("Queue order updated.")

        def action_focus_queue(self) -> None:
            self.query_one("#queue", DataTable).focus()

        def action_focus_history(self) -> None:
            self.query_one("#history", DataTable).focus()

        def action_cancel_input(self) -> None:
            if self.input_mode:
                self.input_mode = ""
                field = self.query_one("#command", Input)
                field.value = ""
                field.display = False
                self.query_one("#library", DataTable).focus()
                self.set_status("Cancelled.")
            else:
                self.query_one("#search", Input).value = ""
                self.query_one("#library", DataTable).focus()
                self.refresh_dashboard()

        def action_help(self) -> None:
            self.set_status("↑↓ select · Enter play/load · / search · A add URL/playlist · N save queue · L load playlist · X delete/remove · Ctrl+↑/↓ reorder · Q queue · H history · Ctrl+O folder")

        def action_open_library_folder(self) -> None:
            try:
                os.startfile(str(LIBRARY_DIR))
                self.set_status(f"Opened {LIBRARY_DIR}")
            except (AttributeError, OSError) as exc:
                self.set_status(f"Could not open folder: {exc}")

        def action_enter(self) -> None:
            panel = self.focused_panel()
            if panel == "library":
                row = self.selected_row("library")
                if row is None:
                    self.set_status("Your library is empty. Press A to add a YouTube URL.")
                    return
                path_value = str(row[0])  # title is displayed; use the selected table row key below
                table = self.query_one("#library", DataTable)
                row_key = list(table.rows.keys())[table.cursor_row]
                item = next((i for i in self.visible_library_items if str(i["path"]) == str(row_key.value)), None)
                if item:
                    launch_player_process([{"path": item["path"], "title": item.get("title")}])
                    self.set_status(f"Playing “{item.get('title') or Path(item['path']).stem}” in the video window.")
            elif panel == "history":
                table = self.query_one("#history", DataTable)
                if table.row_count == 0:
                    self.set_status("No watch history yet.")
                    return
                row_key = list(table.rows.keys())[table.cursor_row]
                entry = next((h for h in self.history_items if str(h["path"]) == str(row_key.value)), None)
                if entry:
                    launch_player_process([{"path": entry["path"], "title": entry.get("title")}])
                    self.set_status(f"Playing “{entry.get('title') or Path(entry['path']).stem}”. Resume is intentionally left unchanged for now.")
            elif panel == "playlists":
                self.action_load_playlist()
            elif panel == "queue":
                self.play_queue_worker()

        def save_playlist_named(self, name: str) -> None:
            queue = load_queue()
            if not queue:
                self.set_status("Queue is empty; nothing to save.")
                return
            playlists = load_playlists()
            playlists[name] = list(queue)
            save_json_atomic(PLAYLISTS_PATH, playlists)
            self.refresh_dashboard()
            self.set_status(f"Saved playlist “{name}”.")

        def delete_selected_playlist(self) -> None:
            table = self.query_one("#playlists", DataTable)
            if table.row_count == 0:
                self.set_status("No playlist selected.")
                return
            row_key = list(table.rows.keys())[table.cursor_row]
            name = str(row_key.value)
            playlists = load_playlists()
            if name not in playlists:
                self.set_status("That playlist no longer exists.")
                return
            del playlists[name]
            save_json_atomic(PLAYLISTS_PATH, playlists)
            self.refresh_dashboard()
            self.set_status(f"Deleted playlist “{name}”. Downloaded videos were not deleted.")

        def delete_selected_video(self) -> None:
            table = self.query_one("#library", DataTable)
            if table.row_count == 0:
                self.set_status("No video selected.")
                return
            row_key = list(table.rows.keys())[table.cursor_row]
            selected_path = str(row_key.value)
            items = load_library()
            item = next((i for i in items if str(i.get("path")) == selected_path), None)
            if item is None:
                self.set_status("That library item no longer exists.")
                return
            try:
                Path(selected_path).unlink(missing_ok=True)
            except OSError as exc:
                self.set_status(f"Could not delete video: {exc}")
                return
            items = [i for i in items if str(i.get("path")) != selected_path]
            save_library(items)
            self.refresh_dashboard()
            self.set_status(f"Deleted “{item.get('title') or Path(selected_path).stem}” from the library.")

        @work(thread=True, exclusive=True)
        def add_url_worker(self, url: str) -> None:
            try:
                entries = expand_youtube_playlist(url)
                if not entries:
                    self.call_from_thread(self.set_status, "No available videos found at that URL.")
                    return
                queue = load_queue()
                queue.extend(entries)
                save_queue(queue)
                message = f"Added {len(entries)} video(s) to the queue. They will download when you play the queue."
                self.call_from_thread(self.refresh_dashboard)
                self.call_from_thread(self.set_status, message)
            except Exception as exc:
                self.call_from_thread(self.set_status, f"Could not read that URL: {exc}")

        @work(thread=True, exclusive=True)
        def play_queue_worker(self) -> None:
            import contextlib
            import io
            queue = load_queue()
            if not queue:
                self.call_from_thread(self.set_status, "Queue is empty. Press A to add a video or playlist URL.")
                return
            self.call_from_thread(self.set_status, f"Preparing {len(queue)} queued video(s) at up to 1080p…")
            items = load_library()
            playable = []
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    for index, entry in enumerate(queue, 1):
                        self.call_from_thread(self.set_status, f"Downloading/preparing video {index} of {len(queue)}…")
                        try:
                            video_path, title, items = download_or_reuse(entry.get("url", ""), 1080, items)
                            playable.append({"path": video_path, "title": title})
                        except Exception:
                            continue
                if not playable:
                    self.call_from_thread(self.set_status, "No queued videos could be prepared. Check the URLs or your connection.")
                    return
                launch_player_process(playable)
                self.call_from_thread(self.set_status, f"Started playback of {len(playable)} prepared video(s).")
                self.call_from_thread(self.refresh_dashboard)
            except Exception as exc:
                self.call_from_thread(self.set_status, f"Queue playback failed: {exc}")

    class TermTubeAppWithEnter(TermTubeApp):
        # Textual's DataTable consumes Enter for row selection in some versions;
        # bind a named action to keep playback behavior consistent.
        BINDINGS = TermTubeApp.BINDINGS + [Binding("enter", "enter", "Play / select", show=False)]

    TermTubeAppWithEnter().run()


def simple_main():
    """Simple, persistent menu: clear actions without a complex dashboard."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) >= 3 and sys.argv[1] == "--play-queue":
        run_qt_player_from_args(sys.argv[2])
        return

    while True:
        items = load_library()
        queue = load_queue()
        playlists = load_playlists()
        videos_count = sum(1 for item in items if library_item_path(item))

        print("\n" + "=" * 44)
        print("  TERMTUBE")
        print("=" * 44)
        print(f"  Library: {videos_count} videos   Queue: {len(queue)}   Playlists: {len(playlists)}")
        print("\n  1  Play a downloaded video")
        print("  2  Download and play a YouTube URL")
        print("  3  Queue and playlists")
        print("  4  Watch history")
        print("  5  Delete a downloaded video")
        print("  6  Open video library folder")
        print("  0  Exit")
        choice = input("\nChoose an option [1-6, 0 to exit]: ").strip().lower()

        if choice in ("0", "x", "exit", "q"):
            print("See you next time.")
            return

        if choice == "1":
            item = choose_library_item(items)
            if not item:
                continue
            path = library_item_path(item)
            if path is None:
                print("That video file is no longer available.")
                continue
            launch_player_process([{"path": str(path), "title": item.get("title") or path.stem}])
            continue

        if choice == "2":
            url = input("Paste a YouTube video or playlist URL: ").strip()
            if not url.startswith(("https://", "http://")):
                print("Please paste a valid http(s) URL.")
                continue
            try:
                max_height = choose_quality()
                # Playlist URLs should be handled by the queue manager so every item
                # can be prepared and played in order.
                info = None
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist", "noplaylist": False, "js_runtimes": {"deno": {}}}) as ydl:
                    info = ydl.extract_info(url, download=False)
                entries = info.get("entries") if isinstance(info, dict) else None
                if entries:
                    queue_entries = expand_youtube_playlist(url)
                    save_queue(queue_entries)
                    print(f"Added {len(queue_entries)} playlist videos. Preparing the queue…")
                    playable, items = download_queue(queue_entries, load_library(), max_height)
                    if playable:
                        launch_player_process(playable)
                    else:
                        print("No videos could be prepared from that playlist.")
                else:
                    path, title, items = download_or_reuse(url, max_height, items)
                    launch_player_process([{"path": path, "title": title}])
            except KeyboardInterrupt:
                print("\nCancelled.")
            except Exception as exc:
                print(f"Could not download/play that URL: {exc}")
            continue

        if choice == "3":
            should_play, queue = manage_queue(items)
            if should_play:
                max_height = choose_quality()
                playable, updated_items = download_queue(queue, load_library(), max_height)
                if playable:
                    launch_player_process(playable)
                else:
                    print("No queued videos were ready to play.")
            continue

        if choice == "4":
            entry = show_history_and_select()
            if entry:
                # Resume seeking is intentionally left unchanged for now.
                launch_player_process([{"path": entry["path"], "title": entry.get("title") or Path(entry["path"]).stem}])
            continue

        if choice == "5":
            delete_library_item(items)
            continue

        if choice == "6":
            try:
                os.startfile(str(LIBRARY_DIR))
            except (AttributeError, OSError):
                print(f"Library folder: {LIBRARY_DIR}")
            continue

        print("Choose one of the listed numbers (0–6).")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--play-queue":
        run_qt_player_from_args(sys.argv[2])
        return
    # The default is deliberately simple and does not require Textual.
    simple_main()


if __name__ == "__main__":

    main()
