import os
import sys
import time
from datetime import datetime

try:
    from PyQt5.QtCore import Qt, QPoint, QRect, QTimer
    from PyQt5.QtWidgets import QApplication, QWidget
    from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QFont
except ImportError:
    QApplication = None

from gesture_engine import WritingState

class CanvasOverlay(QWidget):
    def __init__(self, gesture_engine, hand_tracker):
        super().__init__()
        self.gesture_engine = gesture_engine
        self.hand_tracker = hand_tracker

        # Configure transparent frameless window on top
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # Screen dimensions
        desktop = QApplication.desktop()
        self.screen_rect = desktop.screenGeometry()
        self.setGeometry(self.screen_rect)

        # Drawing layer pixmap
        self.ink_canvas = QPixmap(self.screen_rect.size())
        self.ink_canvas.fill(Qt.transparent)

        # UI elements positioning
        # 1. Floating GBWB Icon (Grammarly style) at Top-Left
        self.gbwb_icon_rect = QRect(30, 40, 65, 65)
        self.gbwb_is_hovered = False

        # 2. Red X Deactivation Box at Middle-Right edge
        self.red_x_rect = QRect(self.screen_rect.width() - 55, self.screen_rect.height() // 2 - 25, 45, 45)
        self.red_x_hovered = False

        # 3. Top Stylus Color Palette Bar Animation Opacity
        self.palette_opacity = 0.0
        self.palette_timer = QTimer(self)
        self.palette_timer.timeout.connect(self._animate_palette)
        self.palette_timer.start(30)

        # Status toast message & timer
        self.status_message = "GBWB READY (Hold Index Fingertip Stable to Write)"
        self.status_opacity = 1.0
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._fade_status)

        # Positions
        self.laser_pos = None
        self.eraser_pos = None
        self.prev_write_pos = None

        # Wire callbacks
        self.gesture_engine.on_status_callback = self.show_status
        self.gesture_engine.on_save_callback = self.save_note

        self.setMouseTracking(True)
        self.mouse_pressed = False

    def show_status(self, msg):
        self.status_message = msg
        self.status_opacity = 1.0
        self.status_timer.start(50)
        self.update()

    def _fade_status(self):
        if self.status_opacity > 0.0:
            self.status_opacity -= 0.02
            self.update()
        else:
            self.status_timer.stop()

    def _animate_palette(self):
        target = 1.0 if self.gesture_engine.color_palette_active else 0.0
        if abs(self.palette_opacity - target) > 0.03:
            if self.palette_opacity < target:
                self.palette_opacity += 0.08
            else:
                self.palette_opacity -= 0.08
            self.palette_opacity = max(0.0, min(1.0, self.palette_opacity))
            self.update()

    def update_frame_data(self, hands_data):
        if not hands_data or not self.gesture_engine.is_active:
            self.laser_pos = None
            self.eraser_pos = None
            self.prev_write_pos = None
            self.update()
            return

        primary_hand = hands_data[0]
        idx_smooth = primary_hand['index_tip_smooth']
        
        screen_x = int(idx_smooth[0] * self.screen_rect.width() / 640)
        screen_y = int(idx_smooth[1] * self.screen_rect.height() / 480)
        
        # 1. Update Pen Cursor Position
        self.laser_pos = QPoint(screen_x, screen_y)

        # 2. Natural Handwriting Ink Drawing (WRITING State)
        if self.gesture_engine.writing_state == WritingState.WRITING and not self.gesture_engine.eraser_mode:
            curr_point = QPoint(screen_x, screen_y)
            last_pt = self.gesture_engine.last_stroke_point
            
            if last_pt is not None:
                prev_point = QPoint(last_pt[0], last_pt[1])
                painter = QPainter(self.ink_canvas)
                painter.setRenderHint(QPainter.Antialiasing, True)
                
                pen_color = QColor(self.gesture_engine.current_color)
                pen_color.setAlpha(240)
                pen = QPen(pen_color, 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                painter.setPen(pen)
                painter.drawLine(prev_point, curr_point)
                painter.end()
            self.prev_write_pos = curr_point
        else:
            self.prev_write_pos = None

        # 3. Eraser Mode -> Fist Only Direct Eraser
        if self.gesture_engine.eraser_mode:
            fist_center = self.hand_tracker.get_fist_center(primary_hand['landmarks_px'])
            fist_screen_x = int(fist_center[0] * self.screen_rect.width() / 640)
            fist_screen_y = int(fist_center[1] * self.screen_rect.height() / 480)
            self.eraser_pos = QPoint(fist_screen_x, fist_screen_y)

            painter = QPainter(self.ink_canvas)
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.setBrush(QBrush(Qt.transparent))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(self.eraser_pos, 60, 60)
            painter.end()
        else:
            self.eraser_pos = None

        self.update()

    def mousePressEvent(self, event):
        pos = event.pos()
        if self.gbwb_icon_rect.contains(pos):
            self.gesture_engine.toggle_board()
            self.update()
            return

        if self.gesture_engine.is_active and self.red_x_rect.contains(pos):
            self.gesture_engine.deactivate_board()
            self.update()
            return

        if event.button() == Qt.LeftButton:
            self.mouse_pressed = True

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mouse_pressed = False

    def mouseMoveEvent(self, event):
        pos = event.pos()
        self.gbwb_is_hovered = self.gbwb_icon_rect.contains(pos)
        self.red_x_hovered = self.red_x_rect.contains(pos) if self.gesture_engine.is_active else False
        
        if self.mouse_pressed or not self.gesture_engine.is_active:
            self.gesture_engine.process_mouse_movement(pos.x(), pos.y())

        self.update()

    def save_note(self):
        notes_dir = os.path.join(os.getcwd(), "GBWB notes")
        os.makedirs(notes_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"GBWB_Note_{timestamp}.png"
        filepath = os.path.join(notes_dir, filename)

        screen = QApplication.primaryScreen()
        screenshot = screen.grabWindow(0)

        composite = QPixmap(screenshot.size())
        painter = QPainter(composite)
        painter.drawPixmap(0, 0, screenshot)
        painter.drawPixmap(0, 0, self.ink_canvas)
        painter.end()

        composite.save(filepath, "PNG")
        self.show_status(f"NOTE SAVED: GBWB notes/{filename}")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 1. Render Digital Ink Canvas Layer
        painter.drawPixmap(0, 0, self.ink_canvas)

        # 2. Render Virtual Pen Cursor (STANDBY vs WRITING states)
        if self.gesture_engine.is_active and self.laser_pos:
            active_qcolor = QColor(self.gesture_engine.current_color)
            
            if self.gesture_engine.writing_state == WritingState.WRITING:
                # WRITING Cursor: Solid glowing core with active ink color (Pen Down Touch)
                aura_color = QColor(active_qcolor.red(), active_qcolor.green(), active_qcolor.blue(), 120)
                painter.setBrush(QBrush(aura_color))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(self.laser_pos, 16, 16)

                core_color = QColor(active_qcolor.red(), active_qcolor.green(), active_qcolor.blue(), 255)
                painter.setBrush(QBrush(core_color))
                painter.drawEllipse(self.laser_pos, 6, 6)

            else:
                # STANDBY Cursor: Translucent hover dot with thin ring (Pen Hovering)
                hover_ring = QColor(0, 230, 255, 140)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(hover_ring, 2, Qt.SolidLine))
                painter.drawEllipse(self.laser_pos, 10, 10)

                hover_core = QColor(0, 230, 255, 220)
                painter.setBrush(QBrush(hover_core))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(self.laser_pos, 4, 4)

        # 3. Render Fist Eraser Circle
        if self.gesture_engine.eraser_mode and self.eraser_pos:
            eraser_color = QColor(255, 60, 60, 90)
            painter.setBrush(QBrush(eraser_color))
            painter.setPen(QPen(QColor(255, 255, 255, 220), 2, Qt.DashLine))
            painter.drawEllipse(self.eraser_pos, 60, 60)

        # 4. Render Top Stylus Color Gradient Palette Bar
        if self.palette_opacity > 0.0:
            bar_w = 480
            bar_h = 50
            bar_x = (self.screen_rect.width() - bar_w) // 2
            bar_y = 20
            
            bar_rect = QRect(bar_x, bar_y, bar_w, bar_h)
            bg_alpha = int(220 * self.palette_opacity)
            painter.setBrush(QBrush(QColor(15, 20, 30, bg_alpha)))
            painter.setPen(QPen(QColor(0, 230, 255, int(230 * self.palette_opacity)), 2))
            painter.drawRoundedRect(bar_rect, 15, 15)

            colors = self.gesture_engine.PALETTE_COLORS
            swatch_w = (bar_w - 30) // len(colors)
            for idx, hex_color in enumerate(colors):
                sx = bar_x + 15 + idx * swatch_w
                sy = bar_y + 10
                swatch_rect = QRect(sx + 2, sy, swatch_w - 4, 30)
                
                c = QColor(hex_color)
                c.setAlpha(int(255 * self.palette_opacity))
                painter.setBrush(QBrush(c))
                
                if idx == self.gesture_engine.selected_color_idx:
                    painter.setPen(QPen(QColor(255, 255, 255, int(255 * self.palette_opacity)), 3))
                else:
                    painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(swatch_rect, 8, 8)

        # 5. Render Floating GBWB Icon Widget (Top-Left)
        bg_color = QColor(20, 24, 35, 220) if not self.gbwb_is_hovered else QColor(35, 45, 65, 240)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(QColor(0, 230, 255, 200), 2))
        painter.drawEllipse(self.gbwb_icon_rect)

        dot_color = QColor(0, 255, 120) if self.gesture_engine.is_active else QColor(150, 150, 150)
        painter.setBrush(QBrush(dot_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(self.gbwb_icon_rect.x() + 45, self.gbwb_icon_rect.y() + 10, 10, 10)

        font = QFont("Arial", 11, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(self.gbwb_icon_rect, Qt.AlignCenter, "GBWB")

        # 6. Render Red X Deactivation Box (Middle-Right Edge)
        if self.gesture_engine.is_active:
            box_color = QColor(230, 40, 40, 230) if not self.red_x_hovered else QColor(255, 70, 70, 250)
            painter.setBrush(QBrush(box_color))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawRoundedRect(self.red_x_rect, 8, 8)

            painter.setPen(QPen(QColor(255, 255, 255), 3, Qt.SolidLine, Qt.RoundCap))
            margin = 12
            rx, ry, rw, rh = self.red_x_rect.getRect()
            painter.drawLine(rx + margin, ry + margin, rx + rw - margin, ry + rh - margin)
            painter.drawLine(rx + rw - margin, ry + margin, rx + margin, ry + rh - margin)

        # 7. Render HUD Status Toast Banner
        if self.status_opacity > 0.0:
            toast_w, toast_h = 480, 42
            toast_x = (self.screen_rect.width() - toast_w) // 2
            toast_y = 80 if self.palette_opacity > 0.5 else 30
            toast_rect = QRect(toast_x, toast_y, toast_w, toast_h)

            banner_color = QColor(15, 20, 30, int(200 * self.status_opacity))
            painter.setBrush(QBrush(banner_color))
            painter.setPen(QPen(QColor(0, 230, 255, int(220 * self.status_opacity)), 1))
            painter.drawRoundedRect(toast_rect, 20, 20)

            font = QFont("Arial", 10, QFont.Bold)
            painter.setFont(font)
            text_color = QColor(255, 255, 255, int(255 * self.status_opacity))
            painter.setPen(text_color)
            painter.drawText(toast_rect, Qt.AlignCenter, self.status_message)
