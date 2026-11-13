"""
Traductor de Audio en Tiempo Real (100% Local y Offline).
Captura el audio reproducido por el PC (Teams, Meet, YouTube, Zoom, reproductores)
o micrófono, reconoce voz en inglés con Faster-Whisper, traduce a español con CTranslate2
y proyecta los subtítulos flotantes de alta legibilidad sobre cualquier ventana.
Guarda automáticamente la conversación con identificación de interlocutores en un archivo .txt.
"""

import os
import sys
import queue
import logging
from typing import Dict, Any

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

class FlushingFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

LOG_FILE = os.path.join(APP_DIR, "traductor_audio.log")
log_handlers = [FlushingFileHandler(LOG_FILE, encoding="utf-8", mode="a")]
if sys.stdout is not None:
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=log_handlers
)
logger = logging.getLogger("TraductorAudio.Main")

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from theme_config import load_config, save_config, get_theme_data, THEMES
from audio_capture import AudioCaptureManager
from transcriber_engine import LiveTranscriber
from transcript_logger import TranscriptLogger
from subtitle_window import SubtitleWindow

SOCKET_NAME = "TraductorAudio_SingleInstance_2026"

def ensure_single_instance(app, on_activate_cb) -> bool:
    """Evita ejecuciones duplicadas del programa en segundo plano."""
    test_socket = QLocalSocket()
    test_socket.connectToServer(SOCKET_NAME)
    if test_socket.waitForConnected(400):
        logger.info("Ya existe una instancia de Traductor de Audio activa. Activando ventana...")
        test_socket.write(b"ACTIVATE")
        test_socket.waitForBytesWritten(400)
        test_socket.disconnectFromServer()
        return False

    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer()
    if server.listen(SOCKET_NAME):
        def handle_connection():
            client = server.nextPendingConnection()
            if client:
                if client.waitForReadyRead(300):
                    data = client.readAll().data().decode("utf-8", errors="ignore")
                    if "ACTIVATE" in data:
                        on_activate_cb()
                client.disconnectFromServer()
        server.newConnection.connect(handle_connection)
        app._instance_server = server
        return True
    return True

def create_audio_tray_icon(theme_key: str = "dark_carbon") -> QPixmap:
    """Dibuja un icono vectorial nítido para la bandeja del sistema."""
    t = get_theme_data(theme_key)
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Fondo redondeado
    painter.setBrush(QColor(t.get("card_bg", "#121214")))
    painter.setPen(QColor(t.get("border", "#27272a")))
    painter.drawRoundedRect(2, 2, 28, 28, 8, 8)

    # Símbolo de audio y subtítulo
    painter.setPen(QColor(t.get("text_accent", "#38bdf8")))
    painter.setFont(QFont("Segoe UI Emoji", 13, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "💬")
    painter.end()
    return pixmap

class SignalBridge(QObject):
    subtitle_received = pyqtSignal(str, str, str)  # speaker, text_en, text_es
    audio_level_received = pyqtSignal(float)
    status_received = pyqtSignal(str)

class ApplicationManager:
    def __init__(self, app: QApplication):
        self.app = app
        self.config = load_config()
        self.bridge = SignalBridge()

        # Cola de transferencia entre hilos de audio e IA
        self.audio_queue = queue.Queue(maxsize=300)

        # 1. Registrador de texto
        self.logger_txt = TranscriptLogger(base_dir=self.config.get("transcripts_dir", "transcripciones"))

        # 2. Captura de audio WASAPI Loopback / Micrófono
        self.audio_capture = AudioCaptureManager(
            audio_queue=self.audio_queue,
            sample_rate=16000,
            on_level_changed=lambda lvl: self.bridge.audio_level_received.emit(lvl),
            on_status=lambda msg: self.bridge.status_received.emit(msg)
        )

        # 3. Transcriptor y Traductor Local
        self.transcriber = LiveTranscriber(
            audio_queue=self.audio_queue,
            model_size=self.config.get("model_size", "tiny.en"),
            sample_rate=16000,
            latency_mode=self.config.get("latency_mode", "ultra_fast"),
            on_subtitle_ready=lambda spk, en, es: self.bridge.subtitle_received.emit(spk, en, es),
            on_status=lambda msg: self.bridge.status_received.emit(msg),
            logger=self.logger_txt
        )

        # 4. Ventana Flotante de Subtítulos
        self.subtitle_win = SubtitleWindow(self.config)

        # Conectar señales seguras entre hilos y la interfaz gráfica Qt
        self.bridge.subtitle_received.connect(self.subtitle_win.add_subtitle)
        self.bridge.audio_level_received.connect(self.subtitle_win.update_audio_activity)
        self.bridge.status_received.connect(self._handle_status_update)

        # Conectar controles de la interfaz
        self.subtitle_win.toggle_pause_requested.connect(self._toggle_pause)
        self.subtitle_win.toggle_source_requested.connect(self._toggle_source)
        self.subtitle_win.new_session_requested.connect(self._handle_new_session)
        self.subtitle_win.open_file_requested.connect(self.logger_txt.open_current_file)
        self.subtitle_win.open_folder_requested.connect(self.logger_txt.open_folder)
        self.subtitle_win.theme_changed.connect(self._on_theme_changed)
        self.subtitle_win.latency_mode_changed.connect(self._handle_latency_mode_changed)

        self._setup_tray()

    def _setup_tray(self):
        """Configura el menú y el icono en la bandeja del sistema de Windows."""
        self.tray = QSystemTrayIcon(self.app)
        self.tray.setIcon(QIcon(create_audio_tray_icon(self.config.get("theme", "dark_carbon"))))
        self.tray.setToolTip("Traductor de Audio en Tiempo Real (100% Local / Privado)")

        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #18181b;
                color: #f4f4f5;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #27272a;
                color: #38bdf8;
            }
        """)

        # Acción Mostrar/Ocultar
        self.act_show = tray_menu.addAction("👁️ Mostrar / Ocultar Subtítulos")
        self.act_show.triggered.connect(self._toggle_window_visibility)

        # Acción Pausar/Reanudar
        self.act_pause = tray_menu.addAction("⏸️ Pausar traducción")
        self.act_pause.triggered.connect(self.subtitle_win._on_pause_clicked)

        # Acción Nueva Sesión
        self.act_new_session = tray_menu.addAction("➕ Iniciar nueva sesión (.txt)")
        self.act_new_session.triggered.connect(self.subtitle_win._on_new_session_clicked)

        # Acción Cambiar Fuente
        self.act_source = tray_menu.addAction("🔊 Cambiar Fuente (PC / Mic)")
        self.act_source.triggered.connect(self.subtitle_win._on_source_clicked)

        tray_menu.addSeparator()

        # Abrir archivo .txt actual
        act_open_txt = tray_menu.addAction("📄 Abrir transcripción actual (.txt)")
        act_open_txt.triggered.connect(self.logger_txt.open_current_file)

        # Abrir carpeta
        act_open_dir = tray_menu.addAction("📁 Abrir carpeta de transcripciones")
        act_open_dir.triggered.connect(self.logger_txt.open_folder)

        tray_menu.addSeparator()

        # Salir
        act_quit = tray_menu.addAction("✕ Salir")
        act_quit.triggered.connect(self._quit)

        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._toggle_window_visibility()

    def _toggle_window_visibility(self):
        if self.subtitle_win.isVisible():
            self.subtitle_win.hide()
        else:
            self.activate_window()

    def activate_window(self):
        self.subtitle_win.show()
        self.subtitle_win.raise_()
        self.subtitle_win.activateWindow()

    def _toggle_pause(self):
        is_paused = self.subtitle_win.is_paused
        self.audio_capture.set_paused(is_paused)
        self.act_pause.setText("▶️ Reanudar traducción" if is_paused else "⏸️ Pausar traducción")

    def _toggle_source(self):
        src = self.subtitle_win.current_source
        self.audio_capture.start(source=src)

    def _handle_new_session(self):
        new_file = self.transcriber.start_new_session()
        logger.info(f"Nueva sesión de transcripción iniciada: {new_file}")

    def _on_theme_changed(self, theme_key: str):
        self.tray.setIcon(QIcon(create_audio_tray_icon(theme_key)))

    def _handle_latency_mode_changed(self, mode_key: str):
        self.transcriber.set_latency_mode(mode_key)
        logger.info(f"Modo de latencia actualizado a: {mode_key}")

    def _handle_status_update(self, msg: str):
        logger.info(f"Estado: {msg}")
        self.subtitle_win.set_status_message(msg)

    def start(self):
        logger.info("Iniciando componentes del Traductor de Audio...")

        # 1. Cargar modelos de IA en segundo plano
        def on_models_ready(success, msg):
            if success:
                logger.info("Modelos de IA listos. Iniciando bucle de transcripción...")
                self.transcriber.start()
                # 2. Iniciar captura de audio WASAPI
                src = self.config.get("audio_source", "loopback")
                self.audio_capture.start(source=src)
                # Mensaje de bienvenida en subtítulos
                QTimer.singleShot(500, lambda: self.subtitle_win.add_subtitle(
                    "Sistema",
                    "Audio translator ready. Speak or play sound on your PC to see subtitles.",
                    "Traductor de audio listo. Habla o reproduce sonido en tu PC para ver subtítulos."
                ))
            else:
                logger.error(f"Fallo al cargar modelos: {msg}")

        self.transcriber.initialize_models_async(callback=on_models_ready)

        # Mostrar ventana de subtítulos en pantalla
        self.activate_window()

        return self.app.exec()

    def _quit(self):
        logger.info("Cerrando Traductor de Audio...")
        self.audio_capture.stop()
        self.transcriber.stop()
        self.subtitle_win.save_current_geometry()
        self.app.quit()

if __name__ == "__main__":
    logger.info("=== INICIANDO TRADUCTOR DE AUDIO EN TIEMPO REAL ===")

    # Identificador explícito de proceso para la barra de tareas de Windows
    try:
        import ctypes
        myappid = "traductoraudio.offline.app.1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(create_audio_tray_icon()))

    manager = None

    def on_activate():
        if manager:
            manager.activate_window()

    # Protección de Instancia Única
    if not ensure_single_instance(app, on_activate):
        logger.info("Ya había una instancia corriendo. Esta segunda instancia se cierra de inmediato.")
        sys.exit(0)

    manager = ApplicationManager(app)
    sys.exit(manager.start())
