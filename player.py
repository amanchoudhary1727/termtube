import os
import sys
import tempfile
import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QUrl, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
import yt_dlp


APP_NAME = "TermTube"


class DownloadWorker(QThread):
    progress = Signal(float, str)
    status = Signal(str)
    finished_file = Signal(str, str)
    failed = Signal(str)

    def __init__(self, url: str, output_dir: str):
        super().__init__()
        self.url = url
        self.output_dir = output_dir
        self._last_percent = -1

    def _progress_hook(self, data):
        state = data.get("status")

        if state == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)
            percent = (downloaded / total * 100) if total else 0
            speed = data.get("speed")
            speed_text = f"{speed / 1024 / 1024:.1f} MB/s" if speed else "calculating speed…"
            self.progress.emit(percent, speed_text)

        elif state == "finished":
            self.status.emit("Download finished; merging audio and video…")

    def run(self):
        options = {
            # Prefer H.264 MP4 video + M4A audio, matching the format that
            # was tested successfully. Fall back to a single MP4, then best.
            "format": (
                "bestvideo[vcodec^=avc1][height<=720][ext=mp4]+"
                "bestaudio[ext=m4a]/best[ext=mp4]/best"
            ),
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(self.output_dir, "video.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
            # Use Deno if it is installed and available on PATH.
            "js_runtimes": {"deno": {}},
        }

        try:
            self.status.emit("Connecting to YouTube…")
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(self.url, download=True)

            title = info.get("title") or "YouTube video"
            candidates = [
                p for p in Path(self.output_dir).glob("video.*")
                if p.is_file() and not p.name.endswith((".part", ".ytdl"))
            ]

            # Prefer the merged MP4; allow a different extension if the
            # selected fallback format did not produce MP4.
            candidates.sort(key=lambda p: (p.suffix.lower() != ".mp4", p.stat().st_size), reverse=False)
            if not candidates:
                raise RuntimeError("yt-dlp finished but no playable output file was found.")

            self.finished_file.emit(str(candidates[0]), title)

        except Exception as exc:
            self.failed.emit(str(exc))


class PlaybackWindow(QMainWindow):
    def __init__(self, player: QMediaPlayer, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Playback")
        self.resize(960, 600)
        self.player = player

        self.video_widget = QVideoWidget()
        self.player.setVideoOutput(self.video_widget)
        self.setCentralWidget(self.video_widget)

    def closeEvent(self, event):
        self.player.pause()
        event.accept()


class TermTubeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(620, 245)
        self.setMinimumWidth(520)

        self.temp_dir = tempfile.mkdtemp(prefix="termtube_")
        self.worker = None
        self.current_file = None

        self.audio = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio)
        self.playback_window = PlaybackWindow(self.player)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        heading = QLabel("TermTube")
        heading.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        subtitle = QLabel("YouTube playback without opening a browser")
        subtitle.setStyleSheet("color: #888;")

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste a YouTube video URL…")
        self.url_input.returnPressed.connect(self.start_download)

        self.play_button = QPushButton("Download & Play")
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.clicked.connect(self.start_download)

        row = QHBoxLayout()
        row.addWidget(self.url_input, 1)
        row.addWidget(self.play_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888;")

        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addLayout(row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        self.setCentralWidget(root)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #151515; color: #f2f2f2; }
            QLineEdit {
                background: #222; border: 1px solid #383838;
                border-radius: 7px; padding: 10px; color: #fff;
            }
            QPushButton {
                background: #e53935; color: white; border: none;
                border-radius: 7px; padding: 10px 14px; font-weight: 600;
            }
            QPushButton:disabled { background: #555; color: #aaa; }
            QProgressBar {
                background: #292929; border: none; border-radius: 5px;
                height: 16px; text-align: center; color: white;
            }
            QProgressBar::chunk { background: #e53935; border-radius: 5px; }
        """)

        self.player.errorOccurred.connect(self.on_player_error)

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            self.status_label.setText("Paste a YouTube URL first.")
            return

        if not (url.startswith("https://") or url.startswith("http://")):
            self.status_label.setText("Please enter a valid http(s) URL.")
            return

        if self.worker and self.worker.isRunning():
            return

        self.play_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting download…")

        self.worker = DownloadWorker(url, self.temp_dir)
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.status_label.setText)
        self.worker.finished_file.connect(self.play_downloaded_file)
        self.worker.failed.connect(self.download_failed)
        self.worker.start()

    def update_progress(self, percent, speed_text):
        self.progress_bar.setValue(max(0, min(100, int(percent))))
        self.status_label.setText(f"Downloading — {percent:.1f}% · {speed_text}")

    def play_downloaded_file(self, file_path, title):
        self.current_file = file_path
        self.play_button.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Playing: {title}")
        self.playback_window.setWindowTitle(f"{APP_NAME} — {title}")
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.playback_window.show()
        self.playback_window.raise_()
        self.playback_window.activateWindow()
        self.player.play()

    def download_failed(self, message):
        self.play_button.setEnabled(True)
        self.status_label.setText("Download failed.")
        QMessageBox.critical(
            self,
            "TermTube — Download failed",
            "Could not download or prepare this video.\n\n"
            f"{message}\n\n"
            "Check your internet connection, yt-dlp/Deno setup, and FFmpeg installation.",
        )

    def on_player_error(self, error, error_string):
        if error != QMediaPlayer.Error.NoError:
            self.status_label.setText(f"Playback error: {error_string}")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(1500)

        self.player.stop()
        self.playback_window.close()
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = TermTubeWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
