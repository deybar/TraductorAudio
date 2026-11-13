"""
Motor de Transcripción Neuronal en Vivo con Faster-Whisper (100% Local).
Arquitectura desacoplada de ultra-baja latencia (Productor-Consumidor no bloqueante).
Segmenta el flujo continuo de audio mediante detección de pausas de voz (VAD rápido),
transcribe a texto en inglés en CPU y coordina con el identificador de hablantes y el traductor.
"""

import threading
import queue
import time
import numpy as np
from typing import Optional, Callable, Dict, Any
from faster_whisper import WhisperModel

from speaker_engine import SpeakerIdentifier
from translator_engine import LocalTranslator
from transcript_logger import TranscriptLogger

# Presets de latencia para ajustar el tiempo de respuesta vs longitud de bloque
LATENCY_PRESETS: Dict[str, Dict[str, Any]] = {
    "ultra_fast": {
        "name": "⚡ Ultra-Rápido (~1s)",
        "min_speech": 0.35,      # 350 ms mínimo de voz
        "max_speech": 2.3,       # Cortar y transcribir a los 2.3s de discurso continuo
        "pause_trigger": 0.28,   # 280 ms de silencio disparan la transcripción de inmediato
        "silence_rms": 0.007     # Umbral de energía de silencio
    },
    "balanced": {
        "name": "⚖️ Equilibrado (~2s)",
        "min_speech": 0.45,
        "max_speech": 3.5,
        "pause_trigger": 0.40,
        "silence_rms": 0.008
    },
    "extended": {
        "name": "📖 Párrafos Largos (~4s)",
        "min_speech": 0.60,
        "max_speech": 5.5,
        "pause_trigger": 0.55,
        "silence_rms": 0.009
    }
}

class LiveTranscriber:
    def __init__(
        self,
        audio_queue: queue.Queue,
        model_size: str = "tiny.en",
        sample_rate: int = 16000,
        latency_mode: str = "ultra_fast",
        on_subtitle_ready: Optional[Callable[[str, str, str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        logger: Optional[TranscriptLogger] = None
    ):
        self.audio_queue = audio_queue
        self.model_size = model_size
        self.sample_rate = sample_rate
        self.latency_mode = latency_mode if latency_mode in LATENCY_PRESETS else "ultra_fast"
        self.on_subtitle_ready = on_subtitle_ready
        self.on_status = on_status
        self.logger = logger

        self.whisper_model: Optional[WhisperModel] = None
        self.speaker_identifier = SpeakerIdentifier()
        self.translator = LocalTranslator()

        # Cola desacoplada para transcripción: la captura/VAD NUNCA se bloquea por la IA
        self._transcribe_queue: queue.Queue = queue.Queue(maxsize=4)

        self.is_running = False
        self.is_model_loaded = False
        self._audio_thread: Optional[threading.Thread] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def update_status(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    def set_latency_mode(self, mode_key: str):
        """Permite cambiar dinámicamente entre 'ultra_fast', 'balanced' o 'extended'."""
        if mode_key in LATENCY_PRESETS:
            self.latency_mode = mode_key
            self.update_status(f"Modo de latencia cambiado a: {LATENCY_PRESETS[mode_key]['name']}")

    def initialize_models_async(self, callback: Optional[Callable[[bool, str], None]] = None):
        """Carga los modelos en segundo plano."""
        def _load():
            try:
                self.update_status(f"Cargando modelo de reconocimiento local '{self.model_size}'...")
                self.whisper_model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                    num_workers=1
                )
                self.update_status("Inicializando traductor local EN -> ES...")
                self.translator._load_or_install_models()
                self.is_model_loaded = True
                self.update_status("Sistemas de IA listos (100% Offline)")
                if callback:
                    callback(True, "Modelos cargados con éxito")
            except Exception as e:
                self.update_status(f"Error al cargar modelos: {e}")
                if callback:
                    callback(False, str(e))

        thread = threading.Thread(target=_load, daemon=True)
        thread.start()

    def start(self):
        """Inicia el bucle de procesamiento de audio en tiempo real y el worker de IA."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True

            # 1. Hilo recolector de audio y segmentador VAD (tiempo real estricto, no bloqueante)
            self._audio_thread = threading.Thread(target=self._process_audio_loop, daemon=True)
            self._audio_thread.start()

            # 2. Hilo consumidor de inferencia neuronal Whisper + Diarización + Traducción
            self._worker_thread = threading.Thread(target=self._transcription_worker_loop, daemon=True)
            self._worker_thread.start()

    def stop(self):
        """Detiene el sistema de transcripción."""
        with self._lock:
            self.is_running = False

    def start_new_session(self) -> Optional[str]:
        """Reinicia el identificador de interlocutores y abre un nuevo archivo .txt de transcripción."""
        self.speaker_identifier.reset()
        if self.logger:
            return self.logger.new_session()
        return None

    def change_model_size(self, new_model_size: str):
        """Permite cambiar entre 'tiny.en', 'base.en' o 'small.en'."""
        if new_model_size != self.model_size:
            self.model_size = new_model_size
            self.is_model_loaded = False
            self.initialize_models_async()

    def target_rate_safe(self) -> int:
        return self.sample_rate if self.sample_rate > 0 else 16000

    def _process_audio_loop(self):
        """
        Bucle de escucha continua y segmentación VAD de ultra-baja latencia:
        Recolecta paquetes de 100 ms sin bloquearse jamás por la inferencia.
        Cuando detecta el final de una frase o se alcanza la duración máxima,
        envía el fragmento a la cola de transcripción en sub-milisegundos.
        """
        buffer_chunks = []
        silence_duration = 0.0
        speech_duration = 0.0

        while self.is_running:
            # Obtener parámetros activos del preset de latencia
            preset = LATENCY_PRESETS.get(self.latency_mode, LATENCY_PRESETS["ultra_fast"])
            silence_threshold = preset["silence_rms"]
            min_speech = preset["min_speech"]
            max_speech = preset["max_speech"]
            pause_trigger = preset["pause_trigger"]

            try:
                # Obtener bloque de audio de la cola (100 ms)
                chunk = self.audio_queue.get(timeout=0.08)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(chunk ** 2)))
            is_speech = (rms >= silence_threshold)
            chunk_duration = len(chunk) / self.target_rate_safe()

            if is_speech:
                buffer_chunks.append(chunk)
                speech_duration += chunk_duration
                silence_duration = 0.0
            else:
                if buffer_chunks:
                    buffer_chunks.append(chunk)
                    silence_duration += chunk_duration

            # Comprobar si debemos disparar la transcripción
            should_transcribe = False
            if speech_duration >= min_speech:
                if silence_duration >= pause_trigger:
                    # Pausa natural del interlocutor detectada con rapidez
                    should_transcribe = True
                elif speech_duration >= max_speech:
                    # Límite máximo de discurso continuo alcanzado
                    should_transcribe = True

            if should_transcribe:
                full_audio = np.concatenate(buffer_chunks)
                pause_time = silence_duration

                # Limpiar acumuladores de inmediato para la siguiente frase
                buffer_chunks = []
                speech_duration = 0.0
                silence_duration = 0.0

                # Desacoplamiento no bloqueante:
                # Si la cola está llena (procesador momentáneamente ocupado), descartar el bloque
                # más antiguo para garantizar que los subtítulos SIEMPRE muestren lo que se dice AHORA
                if self._transcribe_queue.full():
                    try:
                        self._transcribe_queue.get_nowait()
                    except queue.Empty:
                        pass

                self._transcribe_queue.put((full_audio, pause_time))

            elif not is_speech and not buffer_chunks:
                # Silencio ambiental continuo
                silence_duration += chunk_duration

    def _transcription_worker_loop(self):
        """
        Hilo de inferencia neuronal en paralelo:
        Consume los fragmentos de audio de la cola desacoplada y ejecuta
        la diarización, reconocimiento Whisper y traducción sin frenar el flujo de audio.
        """
        while self.is_running:
            try:
                item = self._transcribe_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if not self.whisper_model or not self.is_model_loaded:
                continue

            audio, pause_time = item
            self._transcribe_and_emit(audio, pause_time)

    def _transcribe_and_emit(self, audio: np.ndarray, pause_duration: float):
        """Ejecuta inferencia de voz, identificación de interlocutor y traducción con parámetros optimizados."""
        try:
            # 1. Identificar interlocutor (< 10 ms con la optimización de ventana rápida)
            speaker = self.speaker_identifier.identify_speaker(
                audio,
                sample_rate=self.sample_rate,
                pause_duration=pause_duration
            )

            # 2. Transcribir audio en inglés con faster-whisper
            # Desactivar timestamps y forzar greedy decoding para máxima velocidad en CPU
            audio_duration = len(audio) / self.target_rate_safe()
            # Omitir Silero VAD para fragmentos cortos (<3.5s) ya segmentados por nuestro VAD energético
            use_vad = (audio_duration >= 3.5)

            segments, info = self.whisper_model.transcribe(
                audio,
                beam_size=1,
                best_of=1,
                language="en",
                condition_on_previous_text=False,
                without_timestamps=True,
                temperature=0.0,
                compression_ratio_threshold=2.4,
                no_speech_threshold=0.6,
                vad_filter=use_vad,
                vad_parameters=dict(min_silence_duration_ms=300) if use_vad else None
            )

            text_en_list = []
            for seg in segments:
                text_clean = seg.text.strip()
                if text_clean:
                    text_en_list.append(text_clean)

            if not text_en_list:
                return

            full_text_en = " ".join(text_en_list).strip()
            # Filtro básico de alucinaciones cortas o silencios
            if not full_text_en or full_text_en.lower() in [".", "..", "...", "you", "thank you.", "bye.", "thank you"]:
                if len(audio) < self.sample_rate * 0.7:
                    return

            # 3. Traducir a español localmente con CTranslate2 (< 30 ms)
            full_text_es = self.translator.translate_en_to_es(full_text_en)

            # 4. Registrar en archivo .txt
            if self.logger:
                self.logger.log_entry(speaker, full_text_en, full_text_es)

            # 5. Emitir a la interfaz gráfica de subtítulos
            if self.on_subtitle_ready:
                self.on_subtitle_ready(speaker, full_text_en, full_text_es)

        except Exception as e:
            # Silenciar errores puntuales de frames corruptos
            pass
