#!/usr/bin/env python3
"""Minimal RTSP viewer using PyQt6"""
import argparse
import sys
import time
import cv2
import numpy as np
import psutil
from collections import deque
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                            QWidget, QHBoxLayout, QFrame, QSizePolicy)
from rtsp_client import RTSPClient

class RTSPThread(QThread):
    """Thread for running the RTSP client"""
    frame_received = pyqtSignal(np.ndarray)
    
    def __init__(self, url, latency=100, buffer_size=10):
        super().__init__()
        self.url = url
        self.latency = latency
        self.client = None
        self.buffer_size = buffer_size
        self.frame_buffer = deque(maxlen=buffer_size)
        self.frame_times = deque(maxlen=30)  # Store last 30 frame timestamps
        self.total_frames = 0
        self.dropped_frames = 0
        self.start_time = time.time()
        self.last_frame_time = 0
        self.last_frame_interval = 0
        self.frame_interval_history = deque(maxlen=30)  # For detecting irregular frame timing
        self.buffer_full = False  # Flag to track if we've started emitting frames
        
    def run(self):
        self.client = RTSPClient(self.url, self.latency, self.handle_frame)
        self.client.start()  # This will block until client.stop() is called
        
    def stop(self):
        if self.client:
            self.client.stop()  # Call the RTSPClient's stop method
        
    def handle_frame(self, buffer, rtp_info):
        """Callback for RTSPClient to handle new frames"""
        if buffer is not None:
            # Record frame arrival time
            now = time.time()
            
            # Calculate and store frame interval
            if self.last_frame_time > 0:
                interval = now - self.last_frame_time
                self.last_frame_interval = interval
                self.frame_interval_history.append(interval)
            
            self.frame_times.append(now)
            self.last_frame_time = now
            self.total_frames += 1
            
            # Convert RGB to BGR for OpenCV
            frame = cv2.cvtColor(buffer, cv2.COLOR_RGB2BGR)
            
            # Check if buffer is full (we're falling behind)
            if len(self.frame_buffer) >= self.buffer_size:
                self.dropped_frames += 1
                # Drop oldest frame
                self.frame_buffer.popleft()
            
            # Add to buffer with timestamp
            self.frame_buffer.append((frame, now))
            
            # If buffer is full enough, emit the oldest frame
            buffer_threshold = max(1, int(self.buffer_size * 0.8))  # At least 1 frame, or 80% of buffer
            
            if len(self.frame_buffer) >= buffer_threshold:
                if not self.buffer_full:
                    self.buffer_full = True  # Mark that we've started emitting frames
                
                oldest_frame, timestamp = self.frame_buffer.popleft()
                self.frame_received.emit(oldest_frame)
    
    def get_source_fps(self):
        """Calculate source FPS based on multiple frame intervals"""
        if len(self.frame_times) < 2:
            return 0
            
        # Calculate FPS based on all frames in the time window
        time_diff = self.frame_times[-1] - self.frame_times[0]
        if time_diff > 0:
            return (len(self.frame_times) - 1) / time_diff
        return 0
    
    def get_frame_timing_stability(self):
        """Calculate stability of frame timing (lower is more stable)"""
        if len(self.frame_interval_history) < 2:
            return 0
            
        # Calculate standard deviation of frame intervals
        mean = sum(self.frame_interval_history) / len(self.frame_interval_history)
        variance = sum((x - mean) ** 2 for x in self.frame_interval_history) / len(self.frame_interval_history)
        std_dev = variance ** 0.5
        
        # Return coefficient of variation (std_dev / mean) as percentage
        if mean > 0:
            return (std_dev / mean) * 100
        return 0
    
    def get_stats(self):
        """Get comprehensive statistics about the stream"""
        stats = {}
        
        # Buffer stats
        stats['buffer_size'] = len(self.frame_buffer)
        stats['buffer_capacity'] = self.buffer_size
        stats['buffer_fill_percent'] = (len(self.frame_buffer) / self.buffer_size) * 100 if self.buffer_size > 0 else 0
        stats['buffer_active'] = self.buffer_full
        
        # Frame stats
        stats['total_frames'] = self.total_frames
        stats['dropped_frames'] = self.dropped_frames
        stats['drop_rate'] = (self.dropped_frames / self.total_frames * 100) if self.total_frames > 0 else 0
        stats['source_fps'] = self.get_source_fps()
        
        # Time stats
        stats['uptime'] = time.time() - self.start_time
        
        # Calculate frame delay (time in buffer)
        if self.frame_buffer and len(self.frame_buffer) > 0:
            oldest_frame_time = self.frame_buffer[0][1] if self.frame_buffer else 0
            if oldest_frame_time > 0 and self.last_frame_time > 0:
                stats['frame_delay'] = (self.last_frame_time - oldest_frame_time) * 1000  # in ms
            else:
                stats['frame_delay'] = 0
        else:
            stats['frame_delay'] = 0
            
        # Frame timing stability
        stats['timing_stability'] = self.get_frame_timing_stability()
            
        return stats


class StatsLabel(QLabel):
    """Custom label with background for stats display"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            background-color: rgba(0, 0, 0, 70%);
            color: white;
            border-radius: 5px;
            padding: 3px;
            font-family: monospace;
        """)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class RTSPViewer(QMainWindow):
    """Main application window for RTSP viewing"""
    def __init__(self, url, latency=100, buffer_size=10):
        super().__init__()
        
        # Setup UI with fixed size
        self.setWindowTitle("RTSP Viewer")
        self.setGeometry(100, 100, 800, 600)
        self.setFixedSize(800, 600)  # Set fixed size
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        
        # Create video container frame
        video_frame = QFrame()
        video_frame.setFrameShape(QFrame.Shape.NoFrame)
        video_frame.setStyleSheet("background-color: black;")
        video_layout = QVBoxLayout(video_frame)
        video_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        
        # Create video display label
        self.video_label = QLabel("Connecting to stream...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("color: white; font-size: 16px;")
        video_layout.addWidget(self.video_label)
        
        main_layout.addWidget(video_frame)
        
        # Stats panel
        stats_panel = QFrame()
        stats_panel.setFrameShape(QFrame.Shape.StyledPanel)
        stats_panel.setStyleSheet("background-color: #2a2a2a; color: white;")
        stats_layout = QVBoxLayout(stats_panel)
        
        # Top stats row
        top_stats = QHBoxLayout()
        
        # Left stats
        self.fps_label = StatsLabel("FPS: 0 | Source: 0")
        top_stats.addWidget(self.fps_label)
        
        # Center stats
        self.buffer_label = StatsLabel("Buffer: 0/0 (0%)")
        top_stats.addWidget(self.buffer_label)
        
        # Right stats
        self.status_label = StatsLabel("Status: Good")
        self.status_label.setStyleSheet(self.status_label.styleSheet() + "color: #00ff00;")
        top_stats.addWidget(self.status_label)
        
        stats_layout.addLayout(top_stats)
        
        # Bottom stats row
        bottom_stats = QHBoxLayout()
        
        # Frame stats
        self.frame_stats = StatsLabel("Delay: 0ms | Dropped: 0 (0%)")
        bottom_stats.addWidget(self.frame_stats)
        
        # Performance stats
        self.perf_stats = StatsLabel("CPU: 0% | Render: 0ms")
        bottom_stats.addWidget(self.perf_stats)
        
        stats_layout.addLayout(bottom_stats)
        
        main_layout.addWidget(stats_panel)
        
        # Set size policy for panels
        video_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        stats_panel.setFixedHeight(80)  # Fixed height for stats panel
        
        # FPS calculation variables
        self.frame_count = 0
        self.last_time = time.time()
        self.display_fps = 0
        
        # Performance tracking
        self.process = psutil.Process()
        self.render_times = deque(maxlen=30)
        self.last_cpu_check = time.time()
        
        # Start RTSP thread with buffer
        self.rtsp_thread = RTSPThread(url, latency, buffer_size=buffer_size)
        self.rtsp_thread.frame_received.connect(self.update_frame)
        self.rtsp_thread.start()
        
        # Start timer for stats updates
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(1000)  # Update every second
    
    @pyqtSlot(np.ndarray)
    def update_frame(self, frame):
        """Update the video display with a new frame"""
        # Start timing the frame processing
        start_time = time.time()
        
        # Convert the frame to RGB for display
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Get current size of the video label
        label_width = self.video_label.width()
        label_height = self.video_label.height()
        
        # Resize frame to fit the label
        rgb_frame = cv2.resize(rgb_frame, (label_width, label_height), 
                              interpolation=cv2.INTER_AREA)
        
        h, w, ch = rgb_frame.shape
        
        # Convert to QImage and then QPixmap for display
        bytes_per_line = ch * w
        qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)
        
        # Update the label with the new pixmap
        self.video_label.setPixmap(pixmap)
        
        # Update FPS counter
        self.frame_count += 1
        
        # Record render time (in milliseconds)
        self.render_times.append((time.time() - start_time) * 1000)
    
    @pyqtSlot()
    def update_stats(self):
        """Update statistics display"""
        current_time = time.time()
        elapsed = current_time - self.last_time
        
        if elapsed > 0:
            self.display_fps = int(self.frame_count / elapsed)
            self.frame_count = 0
            self.last_time = current_time
            
            # Get comprehensive stats
            stats = self.rtsp_thread.get_stats()
            source_fps = int(stats['source_fps'])
            
            # Update FPS label
            self.fps_label.setText(f"FPS: {self.display_fps} | Source: {source_fps}")
            
            # Update buffer label
            buffer_size = stats['buffer_size']
            buffer_capacity = stats['buffer_capacity']
            buffer_percent = int(stats['buffer_fill_percent'])
            buffer_status = "Active" if stats['buffer_active'] else "Filling"
            self.buffer_label.setText(f"Buffer: {buffer_size}/{buffer_capacity} ({buffer_percent}%) {buffer_status}")
            
            # Determine performance status
            status = "Good"
            status_color = "#00ff00"  # Green
            
            # Check for dropped frames
            if stats['drop_rate'] > 5:
                status = "Poor (Dropping Frames)"
                status_color = "#ff0000"  # Red
            # Check for performance issues
            elif source_fps > 0 and self.display_fps < source_fps * 0.9:
                status = "Poor (Performance)"
                status_color = "#ff0000"  # Red
            # Check for timing stability
            elif stats['timing_stability'] > 30:  # More than 30% variation
                status = "Fair (Unstable Source)"
                status_color = "#ffa500"  # Orange
            elif source_fps > 0 and self.display_fps < source_fps * 0.95:
                status = "Fair"
                status_color = "#ffa500"  # Orange
                
            # Update status label
            self.status_label.setText(f"Status: {status}")
            self.status_label.setStyleSheet(self.status_label.styleSheet().replace("color: #00ff00;", "").replace("color: #ff0000;", "").replace("color: #ffa500;", "") + f"color: {status_color};")
            
            # Update frame stats
            frame_delay = int(stats['frame_delay'])
            dropped = stats['dropped_frames']
            drop_rate = stats['drop_rate']
            self.frame_stats.setText(f"Delay: {frame_delay}ms | Dropped: {dropped} ({drop_rate:.1f}%)")
            
            # Update performance stats - get CPU usage for this process only
            # Only measure CPU every second to get more accurate readings
            if current_time - self.last_cpu_check >= 1.0:
                cpu_percent = self.process.cpu_percent() / psutil.cpu_count()  # Normalize by CPU count
                self.last_cpu_check = current_time
            else:
                cpu_percent = self.process.cpu_percent(interval=0) / psutil.cpu_count()  # Non-blocking
                
            avg_render_time = sum(self.render_times) / len(self.render_times) if self.render_times else 0
            render_percent = (avg_render_time / (1000 / source_fps)) * 100 if source_fps > 0 else 0
            self.perf_stats.setText(f"CPU: {cpu_percent:.1f}% | Render: {avg_render_time:.1f}ms ({render_percent:.1f}%)")
    
    def closeEvent(self, event):
        """Handle window close event"""
        self.stats_timer.stop()
        self.rtsp_thread.stop()
        self.rtsp_thread.wait(1000)  # Wait up to 1 second for thread to finish
        event.accept()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PyQt6 RTSP Viewer")
    parser.add_argument("--ip", required=True, help="Camera IP")
    parser.add_argument("--username", required=True, help="Username")
    parser.add_argument("--password", required=True, help="Password")
    parser.add_argument("--uri", default="axis-media/media.amp", help="URI path")
    parser.add_argument("--latency", type=int, default=100, help="Latency (ms)")
    parser.add_argument("--buffer", type=int, default=10, help="Frame buffer size")
    args = parser.parse_args()
    
    url = f"rtsp://{args.username}:{args.password}@{args.ip}/{args.uri}"
    
    app = QApplication(sys.argv)
    viewer = RTSPViewer(url, args.latency, args.buffer)
    viewer.show()
    sys.exit(app.exec())