"""
Registro automático de transcripciones y traducciones en archivos .txt.
Organiza las conversaciones con marcas de tiempo e identificación del interlocutor.
"""

import os
import sys
import time
import threading
from datetime import datetime
from typing import Optional

class TranscriptLogger:
    def __init__(self, base_dir: str = "transcripciones"):
        self.base_dir = os.path.abspath(base_dir)
        self.current_filepath: Optional[str] = None
        self._lock = threading.Lock()

        # Rastreador del último interlocutor para formato continuo
        self._last_speaker: Optional[str] = None
        self._last_time: float = 0.0
        self._current_es_len: int = 0

        self._ensure_dir()
        self._init_session_file()

    def _ensure_dir(self):
        if not os.path.exists(self.base_dir):
            try:
                os.makedirs(self.base_dir, exist_ok=True)
            except Exception as e:
                print(f"[ERROR] No se pudo crear carpeta de transcripciones: {e}")

    def _init_session_file(self):
        self._ensure_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"transcripcion_{timestamp}.txt"
        self.current_filepath = os.path.join(self.base_dir, filename)

        sep = "=" * 70
        header = (
            f"{sep}\n"
            f"   TRANSCRIPCIÓN Y TRADUCCIÓN LOCAL EN TIEMPO REAL\n"
            f"   Inicio de sesión: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"   Modo: 100% Offline / Privado (Local en PC)\n"
            f"{sep}\n\n"
        )
        try:
            with open(self.current_filepath, "w", encoding="utf-8") as f:
                f.write(header)
        except Exception as e:
            print(f"[ERROR] Al inicializar archivo de transcripción: {e}")

    def log_entry(self, speaker: str, text_en: str, text_es: str):
        """
        Registra una intervención de forma continua y limpia:
        - Si es la misma persona hablando, anexa el texto sin duplicar marcas de tiempo ni nombres.
        - Solo inserta un nuevo bloque con encabezado cuando cambia de interlocutor o tras una pausa.
        """
        if not self.current_filepath:
            self._init_session_file()

        now = time.time()
        with self._lock:
            # Comprobar si continúa el mismo interlocutor (dentro de 7.5s y < 450 caracteres)
            if (
                self._last_speaker == speaker and
                (now - self._last_time < 7.5) and
                self._current_es_len < 450
            ):
                entry = (
                    f"    {text_en}\n"
                    f" -> {text_es}\n\n"
                )
                self._last_time = now
                self._current_es_len += len(text_es)
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
                entry = (
                    f"[{timestamp}] [{speaker}]\n"
                    f"EN: {text_en}\n"
                    f"ES: {text_es}\n\n"
                )
                self._last_speaker = speaker
                self._last_time = now
                self._current_es_len = len(text_es)

            try:
                with open(self.current_filepath, "a", encoding="utf-8") as f:
                    f.write(entry)
                    f.flush()
            except Exception as e:
                print(f"[ERROR] Al escribir en archivo de transcripción: {e}")

    def get_current_filepath(self) -> Optional[str]:
        return self.current_filepath

    def new_session(self) -> str:
        """Cierra la sesión anterior e inicia una nueva creando un nuevo archivo .txt con timestamp."""
        with self._lock:
            self._last_speaker = None
            self._last_time = 0.0
            self._current_es_len = 0
            self._init_session_file()
            return self.current_filepath

    def open_current_file(self):
        """Abre el archivo .txt de la sesión actual en el Bloc de Notas de Windows."""
        if self.current_filepath and os.path.exists(self.current_filepath):
            try:
                os.startfile(self.current_filepath)
            except Exception as e:
                print(f"[ERROR] Al abrir archivo de transcripción: {e}")

    def open_folder(self):
        """Abre la carpeta de transcripciones en el Explorador de Windows."""
        self._ensure_dir()
        try:
            os.startfile(self.base_dir)
        except Exception as e:
            print(f"[ERROR] Al abrir carpeta de transcripciones: {e}")
