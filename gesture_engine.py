import time
import math

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except ImportError:
    pyautogui = None

class WritingState:
    STANDBY = "STANDBY"
    ACTIVATION = "ACTIVATION"
    WRITING = "WRITING"

class GestureEngine:
    PALETTE_COLORS = [
        "#00E6FF",  # Cyan
        "#FF2E2E",  # Red
        "#FFD700",  # Yellow
        "#00FF7F",  # Spring Green
        "#FF00FF",  # Magenta
        "#FF8C00",  # Dark Orange
        "#FFFFFF",  # Pure White
        "#1E90FF"   # Dodger Blue
    ]

    def __init__(self, on_save_callback=None, on_status_callback=None):
        # System states
        self.is_active = True
        self.eraser_mode = False
        self.color_palette_active = False

        # Natural Handwriting 4-State Machine
        self.writing_state = WritingState.STANDBY
        self.dwell_pos_history = []  # Buffer of (x, y, timestamp) for ~150-300ms dwell detection
        self.last_stroke_point = None

        # Active Stylus Color
        self.selected_color_idx = 0  # Default Cyan

        # Callbacks
        self.on_save_callback = on_save_callback
        self.on_status_callback = on_status_callback

        # Gesture Cooldowns
        self.back_palm_cooldown = 0.0
        self.prev_was_back_palm = False
        self.scroll_cooldown = 0.0
        self.prev_joined_pos = None
        self.zoom_cooldown = 0.0
        self.prev_pinch_dist = None
        self.save_cooldown = 0.0

        # Mouse Star Gesture Tracking
        self.mouse_points = []

    @property
    def current_color(self):
        return self.PALETTE_COLORS[self.selected_color_idx]

    def activate_board(self):
        if not self.is_active:
            self.is_active = True
            self.writing_state = WritingState.STANDBY
            self.eraser_mode = False
            self._notify_status("GBWB SMART BOARD ACTIVATED")

    def deactivate_board(self):
        if self.is_active:
            self.is_active = False
            self.writing_state = WritingState.STANDBY
            self.eraser_mode = False
            self._notify_status("GBWB SMART BOARD STANDBY")

    def toggle_board(self):
        if self.is_active:
            self.deactivate_board()
        else:
            self.activate_board()

    def _notify_status(self, msg):
        if self.on_status_callback:
            self.on_status_callback(msg)

    def process_mouse_movement(self, x, y):
        self.mouse_points.append((x, y, time.time()))
        curr_time = time.time()
        self.mouse_points = [p for p in self.mouse_points if curr_time - p[2] <= 2.5]
        
        if len(self.mouse_points) >= 15:
            if self._detect_star_shape([p[:2] for p in self.mouse_points]):
                self.mouse_points.clear()
                self.activate_board()

    def _detect_star_shape(self, points):
        if len(points) < 15:
            return False
        step = max(1, len(points) // 12)
        sampled = points[::step]
        if len(sampled) < 5:
            return False

        angles = []
        for i in range(1, len(sampled) - 1):
            p1 = sampled[i-1]
            p2 = sampled[i]
            p3 = sampled[i+1]
            v1 = (p1[0] - p2[0], p1[1] - p2[1])
            v2 = (p3[0] - p2[0], p3[1] - p2[1])
            mag1 = math.hypot(v1[0], v1[1])
            mag2 = math.hypot(v2[0], v2[1])
            if mag1 > 15 and mag2 > 15:
                dot = (v1[0]*v2[0] + v1[1]*v2[1]) / (mag1 * mag2)
                dot = max(-1.0, min(1.0, dot))
                angle_deg = math.degrees(math.acos(dot))
                if 20 <= angle_deg <= 80:
                    angles.append(angle_deg)

        return len(angles) >= 4

    def update_gestures(self, hands_data, tracker, screen_w=1920, screen_h=1080):
        now = time.time()
        if not hands_data:
            self.color_palette_active = False
            self.eraser_mode = False
            self.writing_state = WritingState.STANDBY
            self.dwell_pos_history.clear()
            self.last_stroke_point = None
            self.prev_joined_pos = None
            self.prev_pinch_dist = None
            return

        # 1. Two Open Palms Save Note Gesture Check
        if len(hands_data) >= 2:
            h1 = hands_data[0]['landmarks_norm']
            h2 = hands_data[1]['landmarks_norm']
            if tracker.is_open_palm(h1) and tracker.is_open_palm(h2):
                if now - self.save_cooldown > 2.0:
                    self.save_cooldown = now
                    self._notify_status("SAVING NOTE...")
                    if self.on_save_callback:
                        self.on_save_callback()
                    return

        # Process primary hand
        primary = hands_data[0]
        lms_norm = primary['landmarks_norm']
        idx_smooth = primary['index_tip_smooth']
        
        screen_x = int(idx_smooth[0] * screen_w / 640)
        screen_y = int(idx_smooth[1] * screen_h / 480)

        # 2. Pinky Finger -> Show Top Stylus Color Palette
        if tracker.is_pinky_only(lms_norm):
            self.color_palette_active = True
            pinky_norm_x = lms_norm[20][0]
            num_colors = len(self.PALETTE_COLORS)
            new_idx = int(pinky_norm_x * num_colors)
            new_idx = max(0, min(num_colors - 1, new_idx))
            if new_idx != self.selected_color_idx:
                self.selected_color_idx = new_idx
                self._notify_status(f"STYLUS COLOR: {self.current_color}")
        else:
            self.color_palette_active = False

        # 3. Fist Only -> Direct Eraser Mode
        if tracker.is_fist(lms_norm):
            self.eraser_mode = True
            self.writing_state = WritingState.STANDBY
            self.dwell_pos_history.clear()
            self.last_stroke_point = None
            self._notify_status("ERASING (Fist Detected)")
            return
        else:
            self.eraser_mode = False

        if not self.is_active:
            return

        # 4. Natural 4-State Handwriting System (STANDBY -> ACTIVATION -> WRITING -> END STROKE)
        is_index_ext = tracker.is_index_extended(lms_norm)
        
        if is_index_ext and not tracker.is_joined_index_middle(lms_norm) and not self.color_palette_active:
            if self.writing_state == WritingState.STANDBY:
                # Store position history for dwell detection (~150-300ms)
                self.dwell_pos_history.append((screen_x, screen_y, now))
                self.dwell_pos_history = [p for p in self.dwell_pos_history if now - p[2] <= 0.28]

                if len(self.dwell_pos_history) >= 4:
                    duration = now - self.dwell_pos_history[0][2]
                    if duration >= 0.15:
                        # Check stability: max distance between points in buffer
                        xs = [p[0] for p in self.dwell_pos_history]
                        ys = [p[1] for p in self.dwell_pos_history]
                        max_spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))

                        if max_spread <= 10.0:  # Fingertip held stable -> PEN TOUCH ACTIVATION!
                            self.writing_state = WritingState.ACTIVATION
                            self.last_stroke_point = (screen_x, screen_y)
                            self.writing_state = WritingState.WRITING
                            self.dwell_pos_history.clear()
                            self._notify_status("PEN TOUCH DOWN - WRITING")

            elif self.writing_state == WritingState.WRITING:
                if self.last_stroke_point is not None:
                    dist = math.hypot(screen_x - self.last_stroke_point[0], screen_y - self.last_stroke_point[1])
                    # Minimum movement threshold (2.5px) to prevent microscopic hand tremor jitter
                    if dist >= 2.5:
                        # Smooth continuous stroke point
                        self.last_stroke_point = (screen_x, screen_y)

        else:
            # Finger folded / retracted -> END STROKE (Pen Lift)
            if self.writing_state == WritingState.WRITING:
                self.writing_state = WritingState.STANDBY
                self.dwell_pos_history.clear()
                self.last_stroke_point = None
                self._notify_status("PEN LIFTED - STANDBY")
            elif self.writing_state != WritingState.STANDBY:
                self.writing_state = WritingState.STANDBY
                self.dwell_pos_history.clear()
                self.last_stroke_point = None

        # 5. Joined Index + Middle Finger -> Document Scroll & Slide Nav
        if tracker.is_joined_index_middle(lms_norm):
            curr_pos = idx_smooth
            if self.prev_joined_pos is not None:
                dx = curr_pos[0] - self.prev_joined_pos[0]
                dy = curr_pos[1] - self.prev_joined_pos[1]
                
                if now - self.scroll_cooldown > 0.12:
                    if abs(dy) > abs(dx) and abs(dy) > 12:
                        if pyautogui:
                            scroll_amount = -150 if dy > 0 else 150
                            pyautogui.scroll(scroll_amount, x=screen_x, y=screen_y)
                        self.scroll_cooldown = now
                        self._notify_status("DOCUMENT SCROLL")
                    elif abs(dx) > abs(dy) and abs(dx) > 20:
                        if pyautogui:
                            key = 'right' if dx > 0 else 'left'
                            pyautogui.press(key)
                        self.scroll_cooldown = now
                        self._notify_status("NEXT SLIDE" if dx > 0 else "PREV SLIDE")

            self.prev_joined_pos = curr_pos
        else:
            self.prev_joined_pos = None

        # 6. Thumb + Index Pinch -> Document Zoom In / Zoom Out
        states = tracker.get_finger_states(lms_norm)
        if states['thumb'] and states['index'] and not states['middle'] and not states['ring']:
            curr_dist = tracker.get_pinch_distance(lms_norm)
            if self.prev_pinch_dist is not None:
                delta = curr_dist - self.prev_pinch_dist
                if now - self.zoom_cooldown > 0.18:
                    if delta > 0.025:
                        if pyautogui:
                            pyautogui.keyDown('ctrl')
                            pyautogui.scroll(120, x=screen_x, y=screen_y)
                            pyautogui.keyUp('ctrl')
                        self.zoom_cooldown = now
                        self._notify_status("DOCUMENT ZOOM IN")
                    elif delta < -0.025:
                        if pyautogui:
                            pyautogui.keyDown('ctrl')
                            pyautogui.scroll(-120, x=screen_x, y=screen_y)
                            pyautogui.keyUp('ctrl')
                        self.zoom_cooldown = now
                        self._notify_status("DOCUMENT ZOOM OUT")
            self.prev_pinch_dist = curr_dist
        else:
            self.prev_pinch_dist = None
