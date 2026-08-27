import math
import cv2
import numpy as np

try:
    import mediapipe as mp
except ImportError:
    mp = None

class HandTracker:
    def __init__(self, max_hands=2, detection_con=0.7, track_con=0.7):
        self.max_hands = max_hands
        self.detection_con = detection_con
        self.track_con = track_con
        
        if mp is not None:
            self.mp_hands = mp.solutions.hands
            self.hands = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=self.max_hands,
                min_detection_confidence=self.detection_con,
                min_tracking_confidence=self.track_con
            )
            self.mp_draw = mp.solutions.drawing_utils
        else:
            self.hands = None

        # Low-latency position smoothing memory for index fingertip
        self.prev_index_pos = None
        self.smooth_factor = 0.55  # Optimal smooth factor for handwriting speed

    def process_frame(self, frame):
        """
        Processes BGR frame and returns list of hand objects.
        """
        if self.hands is None:
            return []

        h, w, _ = frame.shape
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(img_rgb)
        
        hands_data = []
        
        if results.multi_hand_landmarks:
            for hand_idx, hand_lms in enumerate(results.multi_hand_landmarks):
                handedness_label = "Right"
                if results.multi_handedness:
                    handedness_label = results.multi_handedness[hand_idx].classification[0].label
                
                lms_norm = []
                lms_px = []
                for lm in hand_lms.landmark:
                    lms_norm.append((lm.x, lm.y, lm.z))
                    px = int(lm.x * w)
                    py = int(lm.y * h)
                    lms_px.append((px, py))
                
                # Smooth index tip position (landmark 8)
                raw_idx = lms_px[8]
                if self.prev_index_pos is None:
                    smooth_idx = raw_idx
                else:
                    sx = int(self.prev_index_pos[0] * (1 - self.smooth_factor) + raw_idx[0] * self.smooth_factor)
                    sy = int(self.prev_index_pos[1] * (1 - self.smooth_factor) + raw_idx[1] * self.smooth_factor)
                    smooth_idx = (sx, sy)
                self.prev_index_pos = smooth_idx

                hands_data.append({
                    'landmarks_norm': lms_norm,
                    'landmarks_px': lms_px,
                    'handedness': handedness_label,
                    'index_tip_smooth': smooth_idx,
                    'raw_landmarks': hand_lms
                })

        return hands_data

    @staticmethod
    def get_finger_states(landmarks_norm):
        """
        Determines which fingers are extended.
        Returns dict: {'thumb': bool, 'index': bool, 'middle': bool, 'ring': bool, 'pinky': bool}
        """
        lms = landmarks_norm
        index_ext = lms[8][1] < lms[6][1]
        middle_ext = lms[12][1] < lms[10][1]
        ring_ext = lms[16][1] < lms[14][1]
        pinky_ext = lms[20][1] < lms[18][1]
        
        thumb_pinky_dist = math.hypot(lms[4][0] - lms[17][0], lms[4][1] - lms[17][1])
        thumb_mcp_dist = math.hypot(lms[2][0] - lms[17][0], lms[2][1] - lms[17][1])
        thumb_ext = thumb_pinky_dist > thumb_mcp_dist * 1.1

        return {
            'thumb': thumb_ext,
            'index': index_ext,
            'middle': middle_ext,
            'ring': ring_ext,
            'pinky': pinky_ext
        }

    @staticmethod
    def is_index_extended(landmarks_norm):
        """Returns True if index finger is extended and other fingers (middle, ring, pinky) are folded."""
        states = HandTracker.get_finger_states(landmarks_norm)
        return states['index'] and not states['middle'] and not states['ring']

    @staticmethod
    def is_back_of_palm(landmarks_norm, handedness="Right"):
        """
        Determines if the back of hand / palm is facing the camera.
        """
        lms = landmarks_norm
        v1 = (lms[5][0] - lms[0][0], lms[5][1] - lms[0][1])
        v2 = (lms[17][0] - lms[0][0], lms[17][1] - lms[0][1])
        cross_z = v1[0] * v2[1] - v1[1] * v2[0]
        
        if handedness == "Right":
            return cross_z > 0
        else:
            return cross_z < 0

    @staticmethod
    def is_pinky_only(landmarks_norm):
        """Returns True if Pinky finger is extended while Index, Middle, and Ring fingers are folded."""
        states = HandTracker.get_finger_states(landmarks_norm)
        return states['pinky'] and not states['index'] and not states['middle'] and not states['ring']

    @staticmethod
    def is_fist(landmarks_norm):
        """Returns True if fingers (index, middle, ring, pinky) are folded in a fist."""
        lms = landmarks_norm
        index_folded = lms[8][1] > lms[6][1] or math.hypot(lms[8][0]-lms[0][0], lms[8][1]-lms[0][1]) < math.hypot(lms[6][0]-lms[0][0], lms[6][1]-lms[0][1])
        middle_folded = lms[12][1] > lms[10][1] or math.hypot(lms[12][0]-lms[0][0], lms[12][1]-lms[0][1]) < math.hypot(lms[10][0]-lms[0][0], lms[10][1]-lms[0][1])
        ring_folded = lms[16][1] > lms[14][1] or math.hypot(lms[16][0]-lms[0][0], lms[16][1]-lms[0][1]) < math.hypot(lms[14][0]-lms[0][0], lms[14][1]-lms[0][1])
        pinky_folded = lms[20][1] > lms[18][1] or math.hypot(lms[20][0]-lms[0][0], lms[20][1]-lms[0][1]) < math.hypot(lms[18][0]-lms[0][0], lms[18][1]-lms[0][1])
        return index_folded and middle_folded and ring_folded and pinky_folded

    @staticmethod
    def get_fist_center(landmarks_px):
        """Returns pixel (x, y) center of fist."""
        w = landmarks_px[0]
        i = landmarks_px[5]
        p = landmarks_px[17]
        cx = int((w[0] + i[0] + p[0]) / 3)
        cy = int((w[1] + i[1] + p[1]) / 3)
        return (cx, cy)

    @staticmethod
    def is_open_palm(landmarks_norm):
        states = HandTracker.get_finger_states(landmarks_norm)
        return all(states.values())

    @staticmethod
    def is_joined_index_middle(landmarks_norm):
        states = HandTracker.get_finger_states(landmarks_norm)
        if states['index'] and states['middle'] and not states['ring'] and not states['pinky']:
            dist = math.hypot(landmarks_norm[8][0] - landmarks_norm[12][0], landmarks_norm[8][1] - landmarks_norm[12][1])
            return dist < 0.05
        return False

    @staticmethod
    def get_pinch_distance(landmarks_norm):
        return math.hypot(landmarks_norm[4][0] - landmarks_norm[8][0], landmarks_norm[4][1] - landmarks_norm[8][1])
