import sys
import time
import cv2
import numpy as np

try:
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtWidgets import QApplication, QMessageBox
except ImportError:
    QApplication = None

from hand_tracker import HandTracker
from gesture_engine import GestureEngine
from canvas_overlay import CanvasOverlay

class GBWBApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        
        # Initialize HandTracker and GestureEngine
        self.tracker = HandTracker(max_hands=2, detection_con=0.7, track_con=0.7)
        self.engine = GestureEngine()
        
        # Initialize PyQt5 transparent canvas overlay
        self.overlay = CanvasOverlay(self.engine, self.tracker)
        self.overlay.show()

        # Camera Video Capture
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(0)

        if not self.cap.isOpened():
            print("[Warning] Could not open webcam camera index 0. Running in simulated / manual mode.")
        else:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # 30 FPS Camera Update Loop Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_frame_loop)
        self.timer.start(30)

    def process_frame_loop(self):
        if not self.cap or not self.cap.isOpened():
            return

        ret, frame = self.cap.read()
        if not ret:
            return

        # Mirror frame horizontally for natural gesture interaction
        frame = cv2.flip(frame, 1)

        # Process hand tracking with MediaPipe
        hands_data = self.tracker.process_frame(frame)

        # Evaluate gesture state machine logic
        self.engine.update_gestures(hands_data, self.tracker)

        # Render overlay ink, laser pointer, buttons, and eraser
        self.overlay.update_frame_data(hands_data)

    def run(self):
        print("="*60)
        print("  GBWB (Gesture-Based WhiteBoard) Application Running!")
        print("  - Click GBWB Icon or draw Star with Mouse to Activate")
        print("  - Click Red X Box to Deactivate")
        print("  - Index Finger: Laser Pointer")
        print("  - Double-Tap Index: Toggle Writing ON/OFF")
        print("  - Fist + Open Palm: Eraser Mode")
        print("  - Joined Index+Middle: Scroll / Slide Navigation")
        print("  - Thumb+Index Pinch: Zoom In / Zoom Out")
        print("  - Both Open Palms: Save Note Screenshot to 'GBWB notes'")
        print("="*60)
        sys.exit(self.app.exec_())

if __name__ == "__main__":
    app = GBWBApp()
    app.run()
