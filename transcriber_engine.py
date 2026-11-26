"""
Motor de Transcripción Neuronal en Vivo con Faster-Whisper (100% Local).
Impulsado por Silero VAD v6 (ONNX) neuronal para filtrar música/ruido de fondo,
acondicionamiento acústico (filtro pasa-altos 80Hz + AGC adaptativo),
pre-roll acústico y guardas anti-alucinación.
"""

import re
import threading
import queue
from collections import deque
from typing import Optional, Callable, Dict, Any
import numpy as np
from scipy import signal as scipy_signal
from faster_whisper import WhisperModel
from faster_whisper.vad import get_vad_model

from speaker_engine import SpeakerIdentifier
from translator_engine import LocalTranslator
from transcript_logger import TranscriptLogger

LATENCY_PRESETS: Dict[str, Dict[str, Any]] = {
    "ultra_fast": {
        "name": "⚡ Ultra-Rápido (~1.5s)",
        "min_speech": 0.55,      # 550 ms mínimo de habla neuronal
        "max_speech": 5.2,       # Ventana hasta 5.2s antes de buscar valle entre palabras
        "pause_trigger": 0.35,   # 350 ms de pausa disparan transcripción
        "silence_rms": 0.007     # Umbral fallback solo para tests sintéticos
    },
    "balanced": {
        "name": "⚖️ Equilibrado (~2.5s)",
        "min_speech": 0.75,
        "max_speech": 7.0,
        "pause_trigger": 0.45,
        "silence_rms": 0.008
    },
    "extended": {
        "name": "📖 Párrafos Largos (~4s)",
        "min_speech": 1.00,
        "max_speech": 9.5,
        "pause_trigger": 0.60,
        "silence_rms": 0.009
    }
}

_TECH_PROMPT_EN = (
    "Technical discussion: Raspberry Pi, Arduino, ESP32, microcontroller, "
    "compute module, prototyping, hardware, software, IoT, cloud, API."
)

_HALLUCINATIONS = {
    ".", "..", "...", "you", "thank you.", "thank you", "bye.",
    "thanks for watching.", "subscribe", "subtitles by the amara.org community"
}


def _is_repetitive_hallucination(text: str) -> bool:
    """Detecta alucinaciones repetitivas (n-gramas repetidos >=3 veces) o cadenas vacías."""
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) <= 1:
        return True
    lower = stripped.lower()
    if lower in _HALLUCINATIONS:
        return True

    words = re.findall(r"\w+", lower)
    if len(words) >= 6:
        for n in range(1, 6):
            for i in range(len(words) - 3 * n + 1):
                ngram = words[i : i + n]
                if words[i + n : i + 2 * n] == ngram and words[i + 2 * n : i + 3 * n] == ngram:
                    return True
    return False


class LiveTranscriber:
    def __init__(
        self,
        audio_queue: queue.Queue,
        model_size: str = "base.en",
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

        try:
            self.vad_model = get_vad_model()
        except Exception:
            self.vad_model = None

        nyq = max(4000.0, self.sample_rate / 2.0)
        self._hp_b, self._hp_a = scipy_signal.butter(2, 80.0 / nyq, btype="highpass")

        self._transcribe_queue: queue.Queue = queue.Queue(maxsize=16)

        self.is_running = False
        self.is_model_loaded = False
        self._drain_on_stop = False
        self._last_context_en = ""
        self._last_emitted_en = ""
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

    def _condition_and_normalize_audio(
        self,
        audio: np.ndarray,
        target_peak: float = 0.65,
        max_gain: float = 12.0
    ) -> np.ndarray:
        """Elimina offset DC, ruido sub-80Hz y normaliza ganancia (AGC)."""
        if len(audio) == 0:
            return audio.astype(np.float32)

        clean = audio.astype(np.float32) - float(np.mean(audio))
        if len(clean) > 16:
            clean = scipy_signal.lfilter(self._hp_b, self._hp_a, clean).astype(np.float32)

        peak = float(np.max(np.abs(clean)))
        if peak > 0.0015:
            p95 = float(np.percentile(np.abs(clean), 95))
            ref_level = max(p95 * 1.5, peak * 0.70, 1e-5)
            gain = min(max_gain, target_peak / ref_level)
            clean = np.clip(clean * gain, -0.95, 0.95).astype(np.float32)
        return clean

    def _get_neural_speech_prob(self, chunk: np.ndarray, peak_est: float) -> float:
        """Evalúa presencia de voz humana con Silero VAD v6 (ONNX)."""
        if self.vad_model is None or len(chunk) == 0:
            return 0.0

        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms < 0.0008:
            return 0.0

        chunk_peak = float(np.max(np.abs(chunk)))
        # Ganancia moderada (<= 3.5x) para evitar amplificar ruido de fondo o música sobre el VAD
        gain = min(3.5, 0.25 / max(peak_est, chunk_peak, 0.02))
        amplified = np.clip((chunk.astype(np.float32) - float(np.mean(chunk))) * gain, -0.95, 0.95).astype(np.float32)

        target_len = 1536
        if len(amplified) >= target_len:
            vad_in = amplified[:target_len]
        else:
            vad_in = np.pad(amplified, (0, target_len - len(amplified))).astype(np.float32)

        try:
            probs = self.vad_model(vad_in)
            return float(np.max(probs))
        except Exception:
            return 0.0

    @staticmethod
    def _find_best_valley_cut(
        audio: np.ndarray,
        sample_rate: int = 16000,
        search_back_sec: float = 2.0
    ) -> int:
        """
        Busca el valle acústico de menor energía (130ms + 240ms) en la cola del segmento
        para dividir exactamente entre palabras sin cortar vocablos en inglés.
        """
        n = len(audio)
        margin_end = int(0.14 * sample_rate)
        max_idx = max(1, n - margin_end)
        min_idx = max(int(1.6 * sample_rate), n - int(search_back_sec * sample_rate))
        if min_idx >= max_idx - int(0.1 * sample_rate):
            return n

        w_short = max(1, int(0.13 * sample_rate))
        w_long = max(1, int(0.24 * sample_rate))
        step = max(1, int(0.02 * sample_rate))

        sq = audio[:n].astype(np.float64) ** 2
        cs = np.concatenate(([0.0], np.cumsum(sq)))

        best_cut = n
        min_score = float("inf")
        for center in range(min_idx, max_idx, step):
            s1 = max(0, center - w_short // 2)
            e1 = min(n, center + w_short // 2)
            s2 = max(0, center - w_long // 2)
            e2 = min(n, center + w_long // 2)
            rms_short = (cs[e1] - cs[s1]) / max(1, e1 - s1)
            rms_long = (cs[e2] - cs[s2]) / max(1, e2 - s2)
            score = 0.65 * rms_short + 0.35 * rms_long
            if score < min_score:
                min_score = score
                best_cut = center
        return best_cut

    def initialize_models_async(self, callback: Optional[Callable[[bool, str], None]] = None):
        """Carga los modelos en segundo plano (100% offline si ya están en caché)."""
        def _load():
            try:
                self.update_status(f"Cargando modelo de reconocimiento local '{self.model_size}'...")
                if self.vad_model is None:
                    try:
                        self.vad_model = get_vad_model()
                    except Exception:
                        pass

                try:
                    self.whisper_model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=4,
                        num_workers=1,
                        local_files_only=True
                    )
                except Exception:
                    self.whisper_model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=4,
                        num_workers=1,
                        local_files_only=False
                    )

                self.update_status("Inicializando traductor local EN -> ES...")
                self.translator._load_or_install_models()
                self.is_model_loaded = True
                self.update_status(f"Sistemas de IA listos [{self.model_size}] (100% Offline)")
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
            self._drain_on_stop = False
            self.is_running = True

            self._audio_thread = threading.Thread(target=self._process_audio_loop, daemon=True)
            self._audio_thread.start()

            self._worker_thread = threading.Thread(target=self._transcription_worker_loop, daemon=True)
            self._worker_thread.start()

    def stop(self):
        """Detiene el sistema de transcripción."""
        with self._lock:
            self._drain_on_stop = False
            self.is_running = False

    def flush_and_stop(self, timeout: float = 60.0):
        """Vacía el audio en cola, espera la inferencia pendiente y detiene los hilos."""
        with self._lock:
            self._drain_on_stop = True
            self.is_running = False
            audio_t = self._audio_thread
            worker_t = self._worker_thread
        if audio_t is not None and audio_t.is_alive():
            audio_t.join(timeout=min(5.0, timeout))
        if worker_t is not None and worker_t.is_alive():
            worker_t.join(timeout=timeout)

    def start_new_session(self) -> Optional[str]:
        """Reinicia el identificador de interlocutores y abre un nuevo archivo .txt de transcripción."""
        self.speaker_identifier.reset()
        self._last_context_en = ""
        self._last_emitted_en = ""
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
        Bucle de escucha continua y segmentación neuronal Silero VAD:
        Recolecta paquetes de 100 ms con pre-roll de 200ms sin bloquearse por la inferencia.
        """
        buffer_chunks = []
        pre_roll = deque(maxlen=2)
        silence_duration = 0.0
        speech_duration = 0.0
        peak_est = 0.05

        while self.is_running or (self._drain_on_stop and not self.audio_queue.empty()):
            preset = LATENCY_PRESETS.get(self.latency_mode, LATENCY_PRESETS["ultra_fast"])
            silence_threshold = preset["silence_rms"]
            min_speech = preset["min_speech"]
            max_speech = preset["max_speech"]
            pause_trigger = preset["pause_trigger"]

            try:
                chunk = self.audio_queue.get(timeout=0.08)
            except queue.Empty:
                if not self.is_running:
                    break
                continue

            chunk_peak = float(np.max(np.abs(chunk))) if len(chunk) > 0 else 0.0
            peak_est = max(chunk_peak, peak_est * 0.96)
            rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) > 0 else 0.0

            speech_prob = self._get_neural_speech_prob(chunk, peak_est)
            if self.whisper_model is not None and self.is_model_loaded:
                is_speech = (speech_prob >= 0.42)
            else:
                is_speech = (speech_prob >= 0.42) or (rms >= silence_threshold)

            chunk_duration = len(chunk) / self.target_rate_safe()

            if is_speech:
                if not buffer_chunks:
                    buffer_chunks.extend(list(pre_roll))
                    pre_roll.clear()
                buffer_chunks.append(chunk)
                speech_duration += chunk_duration
                silence_duration = 0.0
            else:
                if buffer_chunks:
                    buffer_chunks.append(chunk)
                    silence_duration += chunk_duration
                    if speech_duration < min_speech and silence_duration >= pause_trigger:
                        buffer_chunks.clear()
                        speech_duration = 0.0
                        silence_duration = 0.0
                else:
                    pre_roll.append(chunk)

            should_transcribe = False
            cut_by_max = False
            if speech_duration >= min_speech:
                if silence_duration >= pause_trigger:
                    should_transcribe = True
                elif speech_duration >= max_speech:
                    should_transcribe = True
                    cut_by_max = True

            if should_transcribe:
                raw_buffer = np.concatenate(buffer_chunks)
                pause_time = silence_duration
                sr = self.target_rate_safe()

                if cut_by_max and len(raw_buffer) > int(2.0 * sr):
                    cut_idx = self._find_best_valley_cut(raw_buffer, sr, search_back_sec=2.0)
                    if 0 < cut_idx < len(raw_buffer) - int(0.10 * sr):
                        full_audio = raw_buffer[:cut_idx]
                        carry_over = raw_buffer[cut_idx:].astype(np.float32)
                        buffer_chunks = [carry_over]
                        speech_duration = len(carry_over) / sr
                        silence_duration = 0.0
                    else:
                        full_audio = raw_buffer
                        buffer_chunks = []
                        speech_duration = 0.0
                        silence_duration = 0.0
                else:
                    full_audio = raw_buffer
                    buffer_chunks = []
                    speech_duration = 0.0
                    silence_duration = 0.0

                if self._transcribe_queue.full():
                    try:
                        self._transcribe_queue.get_nowait()
                    except queue.Empty:
                        pass

                self._transcribe_queue.put((full_audio, pause_time))

        if buffer_chunks and speech_duration >= 0.45:
            full_audio = np.concatenate(buffer_chunks)
            if not self._transcribe_queue.full():
                self._transcribe_queue.put((full_audio, silence_duration))

    def _transcription_worker_loop(self):
        """Hilo consumidor de inferencia neuronal Whisper + Diarización + Traducción."""
        while True:
            try:
                item = self._transcribe_queue.get(timeout=0.1)
            except queue.Empty:
                audio_alive = self._audio_thread is not None and self._audio_thread.is_alive()
                if not self.is_running and not audio_alive:
                    break
                continue

            if not self.whisper_model or not self.is_model_loaded:
                continue

            audio, pause_time = item
            self._transcribe_and_emit(audio, pause_time)

    def _transcribe_and_emit(self, audio: np.ndarray, pause_duration: float):
        """Ejecuta acondicionamiento, identificación de hablante, Whisper y traducción."""
        try:
            conditioned_audio = self._condition_and_normalize_audio(audio)

            speaker = self.speaker_identifier.identify_speaker(
                conditioned_audio,
                sample_rate=self.sample_rate,
                pause_duration=pause_duration
            )

            prev_ctx = self._last_context_en[-140:] if self._last_context_en else ""
            prompt_ctx = f"{_TECH_PROMPT_EN} {prev_ctx}".strip()
            segments, info = self.whisper_model.transcribe(
                conditioned_audio,
                beam_size=2,
                best_of=2,
                language="en",
                initial_prompt=prompt_ctx,
                condition_on_previous_text=False,
                without_timestamps=True,
                temperature=0.0,
                repetition_penalty=1.16,
                no_repeat_ngram_size=3,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.0,
                no_speech_threshold=0.6,
                vad_filter=False
            )

            text_en_list = []
            logprobs = []
            no_speech_probs = []
            for seg in segments:
                text_clean = seg.text.strip()
                if not text_clean:
                    continue
                if getattr(seg, "compression_ratio", 1.0) > 2.0:
                    continue
                if getattr(seg, "no_speech_prob", 0.0) > 0.75:
                    continue
                if _is_repetitive_hallucination(text_clean):
                    continue
                text_en_list.append(text_clean)
                logprobs.append(getattr(seg, "avg_logprob", -0.5))
                no_speech_probs.append(getattr(seg, "no_speech_prob", 0.1))

            if not text_en_list:
                return

            full_text_en = " ".join(text_en_list).strip()
            if _is_repetitive_hallucination(full_text_en):
                return
            if full_text_en.lower() == self._last_emitted_en.lower():
                return

            self._last_emitted_en = full_text_en
            mean_logprob = sum(logprobs) / len(logprobs) if logprobs else -1.0
            max_no_speech = max(no_speech_probs) if no_speech_probs else 1.0
            if mean_logprob > -0.85 and max_no_speech < 0.45:
                self._last_context_en = (self._last_context_en + " " + full_text_en).strip()[-240:]

            full_text_es = self.translator.translate_en_to_es(full_text_en)

            if self.logger:
                self.logger.log_entry(speaker, full_text_en, full_text_es)

            if self.on_subtitle_ready:
                self.on_subtitle_ready(speaker, full_text_en, full_text_es)

        except Exception:
            pass
