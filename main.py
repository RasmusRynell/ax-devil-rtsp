#!/usr/bin/env python3
import sys
import cv2
import time
import threading
import argparse
from datetime import datetime
from PyQt6 import QtWidgets, QtGui, QtCore
from gstreamer import RTSPClient

# Thread-safe fixed-size ring buffer for frames.
class RingBuffer:
    def __init__(self, size):
        self.size = size
        self.buffer = [None] * size
        self.write_index = 0
        self.update_count = 0
        self.last_read_count = 0
        self.lock = threading.Lock()

    def update(self, frame):
        with self.lock:
            self.buffer[self.write_index] = frame
            self.write_index = (self.write_index + 1) % self.size
            self.update_count += 1

    def get_update_count(self):
        with self.lock:
            return self.update_count

    def read_frame(self):
        with self.lock:
            if self.update_count == self.last_read_count:
                return None
            self.last_read_count += 1
            return self.buffer[(self.write_index - 1) % self.size]

# Window for displaying timing and frame metrics.
class MetricsWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Metrics")
        central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)
        self.metrics_label = QtWidgets.QLabel("Metrics will be displayed here")
        layout.addWidget(self.metrics_label)

    def update_metrics(self, text: str):
        self.metrics_label.setText(text)

# Main video window that displays frames received via GStreamer.
class VideoWindow(QtWidgets.QMainWindow):
    def __init__(self, rtsp_url, metrics_window):
        super().__init__()
        self.setWindowTitle("RTSP Video")
        self.setMinimumSize(320, 240)

        central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)

        self.video_label = QtWidgets.QLabel()
        self.video_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                       QtWidgets.QSizePolicy.Policy.Expanding)
        self.video_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.video_label)

        # Initialize the ring buffer and RTSP client.
        self.buffer = RingBuffer(100)
        self.latest_rtp_data = None
        self.rtsp_client = RTSPClient(rtsp_url, frame_handler_callback=self.on_new_frame)
        self.rtsp_thread = threading.Thread(target=self.rtsp_client.start, daemon=True)
        self.rtsp_thread.start()

        # Timing and counter variables.
        self.consumer_last_update = 0
        self.prev_producer_update = 0
        self.consumer_try_reads = 0
        self.consumer_new_frame_reads = 0
        self.total_get_time = 0.0
        self.total_display_time = 0.0
        self.start_time = time.time()

        self.metrics_window = metrics_window

        # QTimer triggers frame updates every 10ms.
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(10)

    def on_new_frame(self, frame, rtp_info):
        # Callback from RTSPClient thread; update ring buffer and store latest RTP data.
        self.buffer.update(frame)
        self.latest_rtp_data = rtp_info

    def convert_cv_qt(self, cv_img):
        """Convert from an OpenCV image (assumed to be in RGB) to QImage scaled to video label dimensions."""
        h, w, ch = cv_img.shape
        bytes_per_line = ch * w
        qt_img = QtGui.QImage(cv_img.data, w, h, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
        qt_img = qt_img.scaled(self.video_label.width(), self.video_label.height(),
                               QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        return qt_img

    def update_frame(self):
        current_update = self.buffer.get_update_count()
        self.consumer_try_reads += 1

        if current_update != self.consumer_last_update:
            t0 = time.time()
            frame = self.buffer.read_frame()
            t1 = time.time()
            get_time = t1 - t0
            self.total_get_time += get_time
            self.consumer_last_update = current_update

            if frame is not None:
                self.consumer_new_frame_reads += 1
                # Make a writable copy of the frame to allow modifications.
                frame = frame.copy()
                # Overlay the current timestamp on the frame.
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cv2.putText(frame, f"Time: {timestamp}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                t2 = time.time()
                qt_img = self.convert_cv_qt(frame)
                self.video_label.setPixmap(QtGui.QPixmap.fromImage(qt_img))
                t3 = time.time()
                self.total_display_time += (t3 - t2)

        # Update metrics every second.
        elapsed = time.time() - self.start_time
        if elapsed >= 1.0:
            avg_get = self.total_get_time / self.consumer_new_frame_reads if self.consumer_new_frame_reads else 0
            avg_disp = self.total_display_time / self.consumer_new_frame_reads if self.consumer_new_frame_reads else 0
            current_producer_update = self.buffer.get_update_count()
            producer_updates = current_producer_update - self.prev_producer_update

            rtp_text = ""
            if self.latest_rtp_data:
                rtp_text = f"\nLatest RTP Time: {self.latest_rtp_data.get('human_time', 'N/A')}"
            metrics_text = (
                f"Consumer try reads: {self.consumer_try_reads}\n"
                f"New frames: {self.consumer_new_frame_reads}\n"
                f"Producer updates: {producer_updates}\n"
                f"Avg get time: {avg_get*1000:.2f} ms\n"
                f"Avg display time: {avg_disp*1000:.2f} ms"
                f"{rtp_text}"
            )
            self.metrics_window.update_metrics(metrics_text)

            # Reset counters.
            self.consumer_try_reads = 0
            self.consumer_new_frame_reads = 0
            self.total_get_time = 0.0
            self.total_display_time = 0.0
            self.prev_producer_update = current_producer_update
            self.start_time = time.time()

    def closeEvent(self, event):
        self.rtsp_client.stop()
        self.rtsp_thread.join()
        self.metrics_window.close()
        event.accept()

def main(rtsp_url):
    app = QtWidgets.QApplication(sys.argv)
    metrics_window = MetricsWindow()
    metrics_window.show()
    video_window = VideoWindow(rtsp_url, metrics_window)
    video_window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PyQt6 RTSP video using GStreamer with a separate, resizable metrics window")
    parser.add_argument("--ip", default="172.20.127.235", help="IP address of the RTSP source")
    parser.add_argument("--username", default="root", help="Username for RTSP authentication")
    parser.add_argument("--password", default="fusion", help="Password for RTSP authentication")
    parser.add_argument("--camera", default="1", help="Camera")
    args = parser.parse_args()

    rtsp_url = f"rtsp://{args.username}:{args.password}@{args.ip}/axis-media/media.amp?onvifreplayext=1&camera={args.camera}"
    main(rtsp_url)
