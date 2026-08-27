import os
import unittest
import time
from hand_tracker import HandTracker
from gesture_engine import GestureEngine, WritingState

class TestGBWBHandwritingSystem(unittest.TestCase):
    def setUp(self):
        self.tracker = HandTracker()
        self.engine = GestureEngine()

    def test_initial_standby_state(self):
        self.assertEqual(self.engine.writing_state, WritingState.STANDBY)
        self.assertIsNone(self.engine.last_stroke_point)

    def test_handwriting_dwell_activation_and_writing(self):
        # Simulated hand landmark data for extended index finger
        lms = [(0.5, 0.5, 0.0)] * 21
        lms[0] = (0.5, 0.8, 0.0)
        # Extended index (6,8)
        lms[6] = (0.5, 0.5, 0.0)
        lms[8] = (0.5, 0.3, 0.0)
        # Folded middle, ring, pinky
        for pip, tip in [(10,12), (14,16), (18,20)]:
            lms[pip] = (0.5, 0.5, 0.0)
            lms[tip] = (0.5, 0.6, 0.0)

        hand_data = [{
            'landmarks_norm': lms,
            'landmarks_px': [(300, 300)] * 21,
            'handedness': 'Right',
            'index_tip_smooth': (300, 300)
        }]

        # Feed stable hand position over simulated time window (>150ms)
        t_start = time.time()
        while time.time() - t_start <= 0.2:
            self.engine.update_gestures(hand_data, self.tracker, 1920, 1080)
            time.sleep(0.03)

        # Verify state transitioned from STANDBY to WRITING
        self.assertEqual(self.engine.writing_state, WritingState.WRITING)
        self.assertIsNotNone(self.engine.last_stroke_point)

    def test_pen_lift_stroke_ending(self):
        self.engine.writing_state = WritingState.WRITING
        self.engine.last_stroke_point = (400, 400)

        # Folded index finger landmark (pip < tip)
        folded_lms = [(0.5, 0.5, 0.0)] * 21
        folded_lms[0] = (0.5, 0.8, 0.0)
        folded_lms[6] = (0.5, 0.5, 0.0)
        folded_lms[8] = (0.5, 0.6, 0.0)  # Folded

        hand_data = [{
            'landmarks_norm': folded_lms,
            'landmarks_px': [(400, 400)] * 21,
            'handedness': 'Right',
            'index_tip_smooth': (400, 400)
        }]

        self.engine.update_gestures(hand_data, self.tracker, 1920, 1080)
        
        # Verify pen lift ends stroke and returns to STANDBY
        self.assertEqual(self.engine.writing_state, WritingState.STANDBY)
        self.assertIsNone(self.engine.last_stroke_point)

if __name__ == "__main__":
    unittest.main()
