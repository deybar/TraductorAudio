"""
Ventana Flotante de Subtítulos de Película en Tiempo Real (PyQt6).
Estilo cinematográfico de alta legibilidad sobre cualquier fondo (vídeos, Teams, presentaciones).
Totalmente arrastrable, redimensionable, con barra de herramientas colapsable en icono contenedor,
indicador de estado luminoso minimalista (sin textos que estorben) y soporte para nueva sesión (.txt).
"""

import sys
import os
import time
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser,
    QPushButton, QGraphicsDropShadowEffect, QFrame, QSlider,
    QMenu, QSizeGrip, QSizePolicy
)
from PyQt6.QtGui import QColor, QFont, QCursor, QAction, QIcon, QTextCursor

from theme_config import THEMES, get_theme_data, save_config

class SubtitleTurn:
    """Representa una intervención continua de un interlocutor sin fragmentación."""
    def __init__(self, speaker: str, text_en: str, text_es: str):
        self.speaker = speaker
        self.en_chunks = [text_en] if text_en else []
        self.es_chunks = [text_es] if text_es else []
        self.last_update_time = time.time()

    @property
    def full_text_en(self) -> str:
        return " ".join(self.en_chunks).strip()

    @property
    def full_text_es(self) -> str:
        return " ".join(self.es_chunks).strip()

    def add_chunk(self, text_en: str, text_es: str):
        if text_en:
            self.en_chunks.append(text_en)
        if text_es:
            self.es_chunks.append(text_es)
        self.last_update_time = time.time()

class DraggableHeader(QFrame):
    """Barra superior que permite arrastrar la ventana de subtítulos con el ratón."""
    def __init__(self, parent_window):
        super().__init__()
        self.window = parent_window
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.start_drag(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.window.do_drag(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.end_drag()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class SubtitleWindow(QWidget):
    # Señales para comunicar cambios con el orquestador principal
    toggle_pause_requested = pyqtSignal()
    toggle_source_requested = pyqtSignal()
    new_session_requested = pyqtSignal()
    clear_subtitles_requested = pyqtSignal()
    open_file_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    theme_changed = pyqtSignal(str)
    latency_mode_changed = pyqtSignal(str)

    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        self.theme_data = get_theme_data(self.config.get("theme", "dark_carbon"))

        self._is_dragging = False
        self._drag_start_offset = QPoint(0, 0)
        self.is_paused = False
        self.current_source = self.config.get("audio_source", "loopback")
        self.display_mode = self.config.get("display_mode", "bilingual")
        self.font_size = self.config.get("font_size", 16)
        self.tools_expanded = self.config.get("tools_expanded", False)

        # Historial de turnos continuos para lectura fluida sin filas duplicadas
        self.turns: List[SubtitleTurn] = []
        self.max_saved_turns = 60

        self._init_ui()
        self.apply_theme(self.config.get("theme", "dark_carbon"))
        self.set_window_opacity_percent(self.config.get("opacity", 92))

        # Restaurar posición y tamaño guardados
        x = self.config.get("window_pos_x", 200)
        y = self.config.get("window_pos_y", 780)
        w = self.config.get("window_width", 880)
        h = self.config.get("window_height", 160)
        self.setGeometry(x, y, w, h)

    def _init_ui(self):
        self.setWindowTitle("Subtítulos en Vivo (100% Local)")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # Contenedor estilo tarjeta de cine
        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(10, 6, 10, 8)
        self.card_layout.setSpacing(4)

        # Sombra suave exterior
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(20)
        self.shadow.setColor(QColor(0, 0, 0, 160))
        self.shadow.setOffset(0, 4)
        self.card.setGraphicsEffect(self.shadow)

        # --- BARRA SUPERIOR (HEADER MINIMALISTA) ---
        self.header = DraggableHeader(self)
        self.header.setObjectName("header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        # Tirador de arrastre
        self.drag_icon = QLabel("⠿", self.header)
        self.drag_icon.setToolTip("Arrastra desde aquí para mover los subtítulos")
        self.drag_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #71717a;")
        header_layout.addWidget(self.drag_icon)

        # Indicador de estado y actividad (Solo punto luminoso, sin títulos que ocupen espacio)
        self.status_dot = QLabel("●", self.header)
        self.status_dot.setStyleSheet("color: #10b981; font-size: 14px;")
        self._update_status_tooltip()
        header_layout.addWidget(self.status_dot)

        header_layout.addStretch()

        # =========================================================
        # CONTENEDOR COLAPSABLE DE BOTONES DE HERRAMIENTAS
        # =========================================================
        self.tools_container = QWidget(self.header)
        self.tools_container.setObjectName("tools_container")
        self.tools_layout = QHBoxLayout(self.tools_container)
        self.tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tools_layout.setSpacing(5)

        # 1. Botón Play/Pausa
        self.btn_pause = QPushButton("⏸", self.tools_container)
        self.btn_pause.setToolTip("Pausar / Reanudar traducción")
        self.btn_pause.setFixedSize(26, 22)
        self.btn_pause.clicked.connect(self._on_pause_clicked)
        self.tools_layout.addWidget(self.btn_pause)

        # 2. Botón Nueva Sesión (.txt nuevo)
        self.btn_new_session = QPushButton("➕ Sesión", self.tools_container)
        self.btn_new_session.setToolTip("Iniciar una nueva reunión / sesión (crea un nuevo archivo .txt limpio)")
        self.btn_new_session.setFixedHeight(22)
        self.btn_new_session.setStyleSheet("padding: 2px 6px; font-size: 11px; font-weight: 600;")
        self.btn_new_session.clicked.connect(self._on_new_session_clicked)
        self.tools_layout.addWidget(self.btn_new_session)

        # 3. Botón Fuente de Audio (PC vs Mic)
        self.btn_source = QPushButton("🔊 PC", self.tools_container)
        self.btn_source.setToolTip("Cambiar entre Audio del PC (Loopback) y Micrófono")
        self.btn_source.setFixedHeight(22)
        self.btn_source.setStyleSheet("padding: 2px 6px; font-size: 11px; font-weight: 600;")
        self.btn_source.clicked.connect(self._on_source_clicked)
        self.tools_layout.addWidget(self.btn_source)

        # 4. Botón Modo de Subtítulos (Bilingüe / Solo ES / Solo EN)
        self.btn_mode = QPushButton("Bilingüe", self.tools_container)
        self.btn_mode.setToolTip("Modo: Bilingüe, Solo Español o Solo Inglés")
        self.btn_mode.setFixedHeight(22)
        self.btn_mode.setStyleSheet("padding: 2px 6px; font-size: 11px; font-weight: 600;")
        self.btn_mode.clicked.connect(self._on_mode_clicked)
        self.tools_layout.addWidget(self.btn_mode)

        # 5. Botones de tamaño de fuente
        self.btn_font_minus = QPushButton("A-", self.tools_container)
        self.btn_font_minus.setToolTip("Reducir tamaño del texto")
        self.btn_font_minus.setFixedSize(24, 22)
        self.btn_font_minus.clicked.connect(self._decrease_font)
        self.tools_layout.addWidget(self.btn_font_minus)

        self.btn_font_plus = QPushButton("A+", self.tools_container)
        self.btn_font_plus.setToolTip("Aumentar tamaño del texto")
        self.btn_font_plus.setFixedSize(24, 22)
        self.btn_font_plus.clicked.connect(self._increase_font)
        self.tools_layout.addWidget(self.btn_font_plus)

        # 6. Botón abrir archivo .txt
        self.btn_txt = QPushButton("📄 .txt", self.tools_container)
        self.btn_txt.setToolTip("Abrir el archivo .txt de transcripción de esta sesión")
        self.btn_txt.setFixedHeight(22)
        self.btn_txt.setStyleSheet("padding: 2px 6px; font-size: 11px; font-weight: 600;")
        self.btn_txt.clicked.connect(lambda: self.open_file_requested.emit())
        self.tools_layout.addWidget(self.btn_txt)

        # 7. Botón Limpiar
        self.btn_clear = QPushButton("🗑", self.tools_container)
        self.btn_clear.setToolTip("Limpiar texto en pantalla")
        self.btn_clear.setFixedSize(24, 22)
        self.btn_clear.clicked.connect(self.clear_subtitles)
        self.tools_layout.addWidget(self.btn_clear)

        # 8. Menú de Temas y Transparencia
        self.btn_settings = QPushButton("🎨", self.tools_container)
        self.btn_settings.setToolTip("Temas visuales y opacidad")
        self.btn_settings.setFixedSize(24, 22)
        self.btn_settings.clicked.connect(self._show_settings_menu)
        self.tools_layout.addWidget(self.btn_settings)

        # 9. Botón Minimizar a Bandeja
        self.btn_min = QPushButton("—", self.tools_container)
        self.btn_min.setToolTip("Minimizar a la bandeja del sistema")
        self.btn_min.setFixedSize(24, 22)
        self.btn_min.clicked.connect(self.hide)
        self.tools_layout.addWidget(self.btn_min)

        header_layout.addWidget(self.tools_container)

        # =========================================================
        # BOTÓN CONTENEDOR / TOGGLE DE HERRAMIENTAS
        # =========================================================
        self.btn_toggle_tools = QPushButton("⚙", self.header)
        self.btn_toggle_tools.setObjectName("btn_toggle_tools")
        self.btn_toggle_tools.setToolTip("Mostrar / Ocultar herramientas del subtitulador")
        self.btn_toggle_tools.setFixedSize(26, 22)
        self.btn_toggle_tools.clicked.connect(self.toggle_tools)
        header_layout.addWidget(self.btn_toggle_tools)

        # Botón Cerrar discreto
        self.btn_close = QPushButton("✕", self.header)
        self.btn_close.setToolTip("Cerrar traductor de audio")
        self.btn_close.setFixedSize(24, 22)
        self.btn_close.clicked.connect(self.close)
        header_layout.addWidget(self.btn_close)

        # Aplicar estado colapsado inicial
        self.tools_container.setVisible(self.tools_expanded)
        self._update_toggle_button_visual()

        self.card_layout.addWidget(self.header)

        # --- ÁREA DE SUBTÍTULOS CINEMATOGRÁFICOS ---
        self.subtitles_view = QTextBrowser(self.card)
        self.subtitles_view.setOpenExternalLinks(False)
        self.subtitles_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.subtitles_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.subtitles_view.setFrameShape(QFrame.Shape.NoFrame)
        self.subtitles_view.setPlaceholderText("Esperando audio del PC (Teams, Meet, YouTube, vídeos)...")
        self.card_layout.addWidget(self.subtitles_view)

        # Barra inferior con tirador de tamaño
        bottom_frame = QFrame(self.card)
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addStretch()
        
        self.size_grip = QSizeGrip(bottom_frame)
        self.size_grip.setToolTip("Arrastra desde la esquina para cambiar el tamaño")
        bottom_layout.addWidget(self.size_grip)
        self.card_layout.addWidget(bottom_frame)

        main_layout.addWidget(self.card)

    def toggle_tools(self):
        """Muestra u oculta los botones dentro del icono contenedor."""
        self.tools_expanded = self.tools_container.isHidden()
        self.tools_container.setVisible(self.tools_expanded)
        self.config["tools_expanded"] = self.tools_expanded
        save_config(self.config)
        self._update_toggle_button_visual()

    def _update_toggle_button_visual(self):
        t = self.theme_data
        is_open = not self.tools_container.isHidden()
        if is_open:
            self.btn_toggle_tools.setStyleSheet(f"""
                QPushButton#btn_toggle_tools {{
                    background: {t['text_accent']};
                    color: #000000;
                    border: 1px solid {t['text_accent']};
                    font-weight: bold;
                }}
            """)
            self.btn_toggle_tools.setToolTip("Ocultar barra de herramientas")
        else:
            self.btn_toggle_tools.setStyleSheet("")
            self.btn_toggle_tools.setToolTip("Mostrar barra de herramientas (Pausa, Sesión, Modos...)")

    def _update_status_tooltip(self):
        """Actualiza el tooltip del punto de estado sin ensuciar la ventana con texto."""
        if self.is_paused:
            tip = "Traducción en pausa (Clic en herramientas para reanudar)"
        else:
            src_str = "Audio del PC (Loopback)" if self.current_source == "loopback" else "Micrófono"
            tip = f"🟢 Activo: Escuchando {src_str} (EN ➔ ES) - 100% Local"
        self.status_dot.setToolTip(tip)

    def apply_theme(self, theme_key: str):
        """Aplica la paleta de colores y estilos CSS al popup."""
        self.theme_data = get_theme_data(theme_key)
        self.config["theme"] = theme_key
        t = self.theme_data

        card_style = f"""
            QFrame#card {{
                background-color: {t['card_bg']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
            QPushButton {{
                background: {t['header_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 4px;
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QPushButton:hover {{
                background: {t['btn_hover']};
                border-color: {t['text_accent']};
            }}
            QPushButton:pressed {{
                background: {t['text_accent']};
                color: #000000;
            }}
            QLabel {{
                color: {t['text_primary']};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QTextBrowser {{
                background: transparent;
                border: none;
                color: {t['text_primary']};
                font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
                selection-background-color: {t['text_accent']};
                selection-color: #000000;
            }}
        """
        self.card.setStyleSheet(card_style)
        self._update_toggle_button_visual()
        if hasattr(self, "turns") and self.turns:
            self._render_all_subtitles()
        self.save_current_geometry()

    def set_window_opacity_percent(self, opacity_percent: int):
        val = max(50, min(100, opacity_percent))
        self.config["opacity"] = val
        self.setWindowOpacity(val / 100.0)

    def update_audio_activity(self, level: float):
        """Hace parpadear el punto luminoso cuando hay audio presente sin agregar texto."""
        if self.is_paused:
            self.status_dot.setStyleSheet("color: #f59e0b; font-size: 14px;")
            return

        if level > 0.05:
            # Verde vibrante cuando se detecta voz/audio
            self.status_dot.setStyleSheet("color: #22c55e; font-size: 14px; font-weight: bold;")
        else:
            # Verde normal en reposo
            self.status_dot.setStyleSheet("color: #10b981; font-size: 14px;")

    def set_status_message(self, msg: str):
        """Actualiza el tooltip del punto de estado."""
        self.status_dot.setToolTip(msg)

    def add_subtitle(self, speaker: str, text_en: str, text_es: str):
        """
        Inserta un nuevo fragmento o lo concatena al turno activo si es el mismo interlocutor:
        - Si es la misma persona hablando, anexa el texto de forma continua sin repetir la insignia.
        - Solo dibuja una nueva insignia cuando cambia de interlocutor o tras una pausa prolongada.
        """
        if not text_en and not text_es:
            return

        now = time.time()
        is_system = (speaker.lower() == "sistema")

        # Comprobar si continúa el mismo interlocutor:
        # Mismo hablante, turno reciente (< 7.5s) y longitud moderada (< 450 caracteres)
        can_continue = False
        if self.turns and not is_system:
            last_turn = self.turns[-1]
            if (
                last_turn.speaker == speaker and
                last_turn.speaker != "---SESSION_SEPARATOR---" and
                (now - last_turn.last_update_time < 7.5) and
                (len(last_turn.full_text_es) < 450)
            ):
                can_continue = True

        if can_continue:
            self.turns[-1].add_chunk(text_en, text_es)
        else:
            new_turn = SubtitleTurn(speaker, text_en, text_es)
            self.turns.append(new_turn)
            if len(self.turns) > self.max_saved_turns:
                self.turns.pop(0)

        self._render_all_subtitles()

    def _render_all_subtitles(self):
        """
        Renderiza los subtítulos continuos en HTML con estilo cinematográfico de alta legibilidad.
        Muestra la insignia del hablante solo una vez al iniciar su intervención.
        """
        t = self.theme_data
        es_size = self.font_size
        en_size = max(11, self.font_size - 3)

        html_blocks = []

        for turn in self.turns:
            if turn.speaker == "---SESSION_SEPARATOR---":
                html_blocks.append(
                    f"<div style='margin: 14px 0 10px 0; border-top: 1px dashed {t['border']}; "
                    f"text-align: center; color: {t['text_accent']}; font-size: 11px; font-weight: bold;'>"
                    f"✨ NUEVA SESIÓN DE TRANSCRIPCIÓN INICIADA"
                    f"</div>"
                )
                continue

            speaker = turn.speaker
            is_system = (speaker.lower() == "sistema")

            spk_lower = speaker.lower()
            if "1" in spk_lower:
                spk_color = t.get("speaker_1", "#38bdf8")
            elif "2" in spk_lower:
                spk_color = t.get("speaker_2", "#fbbf24")
            elif "3" in spk_lower:
                spk_color = t.get("speaker_3", "#34d399")
            elif "4" in spk_lower:
                spk_color = t.get("speaker_4", "#f472b6")
            else:
                spk_color = t.get("text_accent", "#38bdf8")

            block = ["<div style='margin-bottom: 12px; line-height: 1.35;'>"]

            # Insignia del Interlocutor (solo UNA vez al comenzar su intervención)
            badge_text = "ℹ Sistema" if is_system else f"● {speaker}"
            block.append(
                f"<div style='margin-bottom: 3px;'>"
                f"<span style='background-color: {t['badge_bg']}; color: {spk_color}; "
                f"border-radius: 3px; padding: 1px 6px; font-size: {en_size}px; font-weight: bold;'>"
                f"{badge_text}</span>"
                f"</div>"
            )

            # Texto en Español continuo
            if self.display_mode in ("bilingual", "spanish_only") or is_system:
                block.append(
                    f"<div style='color: {t['text_primary']}; font-size: {es_size}px; "
                    f"font-weight: 600; letter-spacing: 0.2px; line-height: 1.32; margin-top: 2px;'>"
                    f"{turn.full_text_es}</div>"
                )

            # Texto en Inglés continuo
            if self.display_mode in ("bilingual", "english_only") and not is_system:
                margin_top = "3px" if self.display_mode == "bilingual" else "1px"
                block.append(
                    f"<div style='color: {t['text_secondary']}; font-size: {en_size}px; "
                    f"font-style: italic; margin-top: {margin_top}; line-height: 1.25;'>"
                    f"&ldquo;{turn.full_text_en}&rdquo;</div>"
                )

            block.append("</div>")
            html_blocks.append("".join(block))

        full_html = "".join(html_blocks)

        # Respetar la posición del scroll del usuario
        scroll_bar = self.subtitles_view.verticalScrollBar()
        was_at_bottom = (scroll_bar.value() >= scroll_bar.maximum() - 40) or (scroll_bar.maximum() == 0)

        self.subtitles_view.setHtml(full_html)

        if was_at_bottom:
            self.subtitles_view.moveCursor(QTextCursor.MoveOperation.End)

    def clear_subtitles(self):
        self.turns.clear()
        self.subtitles_view.clear()
        self.clear_subtitles_requested.emit()

    def _on_pause_clicked(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.setText("▶")
            self.btn_pause.setToolTip("Reanudar traducción")
            self.status_dot.setStyleSheet("color: #f59e0b; font-size: 14px;")
        else:
            self.btn_pause.setText("⏸")
            self.btn_pause.setToolTip("Pausar traducción")
            self.status_dot.setStyleSheet("color: #10b981; font-size: 14px;")

        self._update_status_tooltip()
        self.toggle_pause_requested.emit()

    def _on_new_session_clicked(self):
        """Inicia una nueva sesión creando un nuevo archivo .txt y agregando un separador visual."""
        sep_turn = SubtitleTurn("---SESSION_SEPARATOR---", "", "")
        self.turns.append(sep_turn)
        self._render_all_subtitles()
        self.new_session_requested.emit()

    def _on_source_clicked(self):
        if self.current_source == "loopback":
            self.current_source = "microphone"
            self.btn_source.setText("🎙 Mic")
        else:
            self.current_source = "loopback"
            self.btn_source.setText("🔊 PC")

        self.config["audio_source"] = self.current_source
        self._update_status_tooltip()
        save_config(self.config)
        self.toggle_source_requested.emit()

    def _on_mode_clicked(self):
        modes = ["bilingual", "spanish_only", "english_only"]
        curr_idx = modes.index(self.display_mode) if self.display_mode in modes else 0
        next_mode = modes[(curr_idx + 1) % len(modes)]
        self.display_mode = next_mode
        self.config["display_mode"] = next_mode

        labels = {
            "bilingual": "Bilingüe",
            "spanish_only": "Solo Español",
            "english_only": "Solo Inglés"
        }
        self.btn_mode.setText(labels[next_mode])
        save_config(self.config)
        self._render_all_subtitles()

    def _increase_font(self):
        if self.font_size < 28:
            self.font_size += 2
            self.config["font_size"] = self.font_size
            save_config(self.config)
            self._render_all_subtitles()

    def _decrease_font(self):
        if self.font_size > 12:
            self.font_size -= 2
            self.config["font_size"] = self.font_size
            save_config(self.config)
            self._render_all_subtitles()

    def _show_settings_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {self.theme_data['card_bg']};
                color: {self.theme_data['text_primary']};
                border: 1px solid {self.theme_data['border']};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item:selected {{
                background-color: {self.theme_data['btn_hover']};
                color: {self.theme_data['text_accent']};
            }}
        """)

        # Submenú de Temas
        theme_menu = menu.addMenu("🎨 Cambiar Tema")
        for key, data in THEMES.items():
            act = theme_menu.addAction(data["name"])
            act.triggered.connect(lambda checked, k=key: self._set_theme(k))

        # Submenú de Transparencia
        opac_menu = menu.addMenu("🎚️ Opacidad / Transparencia")
        for pct in [100, 92, 85, 75]:
            act = opac_menu.addAction(f"{pct}%")
            act.triggered.connect(lambda checked, p=pct: self.set_window_opacity_percent(p))

        # Submenú de Latencia / Velocidad de Respuesta
        latency_menu = menu.addMenu("⚡ Velocidad de Respuesta (Latencia)")
        latency_options = [
            ("ultra_fast", "⚡ Ultra-Rápida (~1s) [Recomendada]"),
            ("balanced", "⚖️ Equilibrada (~2s)"),
            ("extended", "📖 Párrafos Largos (~4s)")
        ]
        curr_lat = self.config.get("latency_mode", "ultra_fast")
        for key, label in latency_options:
            prefix = "✓ " if key == curr_lat else "   "
            act = latency_menu.addAction(f"{prefix}{label}")
            act.triggered.connect(lambda checked, k=key: self._set_latency_mode(k))

        menu.addSeparator()

        # Abrir carpeta de transcripciones
        act_folder = menu.addAction("📁 Ver carpeta de transcripciones .txt")
        act_folder.triggered.connect(lambda: self.open_folder_requested.emit())

        # Abrir archivo actual
        act_file = menu.addAction("📄 Abrir archivo .txt de esta sesión")
        act_file.triggered.connect(lambda: self.open_file_requested.emit())

        menu.exec(QCursor.pos())

    def _set_theme(self, theme_key: str):
        self.apply_theme(theme_key)
        self.theme_changed.emit(theme_key)

    def _set_latency_mode(self, mode_key: str):
        self.config["latency_mode"] = mode_key
        save_config(self.config)
        self.latency_mode_changed.emit(mode_key)

    def save_current_geometry(self):
        geo = self.geometry()
        self.config["window_pos_x"] = geo.x()
        self.config["window_pos_y"] = geo.y()
        self.config["window_width"] = geo.width()
        self.config["window_height"] = geo.height()
        save_config(self.config)

    # --- LÓGICA DE ARRASTRE DE VENTANA ---
    def start_drag(self, global_pos: QPoint):
        self._is_dragging = True
        self._drag_start_offset = global_pos - self.pos()

    def do_drag(self, global_pos: QPoint):
        if self._is_dragging:
            self.move(global_pos - self._drag_start_offset)

    def end_drag(self):
        self._is_dragging = False
        self.save_current_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.save_current_geometry()
