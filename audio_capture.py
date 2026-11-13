"""
Capturador de Audio en Tiempo Real (WASAPI Loopback para Audio de PC y Micrófono).
Permite capturar el sonido interno de la computadora (Teams, Meet, YouTube, Zoom, reproductores)
o el micrófono físico, remuestreando en vivo a 16kHz mono para los motores de IA.
"""

import threading
import queue
import time
from typing import Optional, Callable, List, Dict
import numpy as np
import pyaudiowpatch as pyaudio
from scipy import signal

class AudioCaptureManager:
    def __init__(
        self,
        audio_queue: queue.Queue,
        sample_rate: int = 16000,
        on_level_changed: Optional[Callable[[float], None]] = None,
        on_status: Optional[Callable[[str], None]] = None
    ):
        self.audio_queue = audio_queue
        self.target_rate = sample_rate
        self.on_level_changed = on_level_changed
        self.on_status = on_status

        self.p: Optional[pyaudio.PyAudio] = None
        self.stream = None
        self.silent_stream = None  # Mantiene activo el reloj WASAPI en momentos de silencio
        self.is_running = False
        self.is_paused = False

        self.current_source = "loopback"  # "loopback" o "microphone"
        self.device_index: Optional[int] = None
        self.native_rate = 48000
        self.channels = 2

        self._lock = threading.Lock()

    def update_status(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    def get_available_devices(self) -> Dict[str, List[Dict]]:
        """Lista los dispositivos loopback y micrófonos disponibles en Windows."""
        p = pyaudio.PyAudio()
        devices = {"loopback": [], "microphone": []}
        try:
            # Loopbacks
            for dev in p.get_loopback_device_info_generator():
                devices["loopback"].append({
                    "index": dev["index"],
                    "name": dev["name"],
                    "rate": int(dev["defaultSampleRate"]),
                    "channels": dev["maxInputChannels"]
                })
            # Micrófonos / Entradas estándar
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if dev["maxInputChannels"] > 0 and not dev.get("isLoopbackDevice", False):
                    devices["microphone"].append({
                        "index": dev["index"],
                        "name": dev["name"],
                        "rate": int(dev["defaultSampleRate"]),
                        "channels": dev["maxInputChannels"]
                    })
        finally:
            p.terminate()
        return devices

    def _find_default_loopback_device(self, p: pyaudio.PyAudio) -> Optional[Dict]:
        """Busca el dispositivo loopback asociado a los altavoces predeterminados de Windows."""
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            
            # Buscar coincidencia exacta por nombre
            for dev in p.get_loopback_device_info_generator():
                if default_speakers["name"] in dev["name"]:
                    return dev

            # Si no coincide por nombre exacto, tomar el primer loopback disponible
            for dev in p.get_loopback_device_info_generator():
                return dev
        except Exception as e:
            self.update_status(f"Error al detectar loopback WASAPI: {e}")
        return None

    def start(self, source: str = "loopback", device_index: Optional[int] = None):
        """Inicia la captura de audio en un hilo de fondo."""
        with self._lock:
            if self.is_running:
                self.stop()

            self.current_source = source
            self.device_index = device_index
            self.is_running = True
            self.is_paused = False

            thread = threading.Thread(target=self._run_capture, daemon=True)
            thread.start()

    def stop(self):
        """Detiene la captura de audio y libera los streams."""
        with self._lock:
            self.is_running = False

        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if self.silent_stream:
            try:
                self.silent_stream.stop_stream()
                self.silent_stream.close()
            except Exception:
                pass
            self.silent_stream = None

        if self.p:
            try:
                self.p.terminate()
            except Exception:
                pass
            self.p = None

    def set_paused(self, paused: bool):
        self.is_paused = paused

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Callback invocado por PyAudio con cada paquete de audio entrante."""
        if not self.is_running or self.is_paused or not in_data:
            return (None, pyaudio.paContinue)

        try:
            # Convertir bytes int16 a numpy array float32 (-1.0 a 1.0)
            audio_data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0

            # Si es estéreo o multicanal, promediar a mono
            if self.channels > 1:
                audio_data = audio_data.reshape(-1, self.channels)
                audio_data = np.mean(audio_data, axis=1)

            # Nivel de volumen RMS para la interfaz
            rms = float(np.sqrt(np.mean(audio_data ** 2)))
            if self.on_level_changed:
                self.on_level_changed(min(1.0, rms * 5.0))

            # Remuestrear a 16000 Hz si la tasa nativa es distinta
            if self.native_rate != self.target_rate:
                # Remuestreo de alta calidad y bajo retardo con scipy
                gcd = np.gcd(self.native_rate, self.target_rate)
                up = self.target_rate // gcd
                down = self.native_rate // gcd
                resampled = signal.resample_poly(audio_data, up, down).astype(np.float32)
            else:
                resampled = audio_data

            # Encolar fragmento para el reconocedor de voz
            self.audio_queue.put(resampled)

        except Exception as e:
            pass

        return (None, pyaudio.paContinue)

    def _run_capture(self):
        try:
            self.p = pyaudio.PyAudio()

            target_device = None
            if self.current_source == "loopback":
                if self.device_index is not None:
                    target_device = self.p.get_device_info_by_index(self.device_index)
                else:
                    target_device = self._find_default_loopback_device(self.p)

                if not target_device:
                    self.update_status("No se encontró dispositivo de audio de altavoces (Loopback).")
                    return

                self.native_rate = int(target_device["defaultSampleRate"])
                self.channels = max(1, target_device["maxInputChannels"])
                self.update_status(f"Capturando audio del PC: {target_device['name']}")

                # Iniciar un stream de salida silencioso para mantener activo el reloj WASAPI
                # Esto garantiza que el loopback continúe emitiendo frames aunque haya silencio en una reunión
                try:
                    wasapi_info = self.p.get_host_api_info_by_type(pyaudio.paWASAPI)
                    self.silent_stream = self.p.open(
                        format=pyaudio.paInt16,
                        channels=2,
                        rate=self.native_rate,
                        output=True,
                        output_device_index=wasapi_info["defaultOutputDevice"],
                        frames_per_buffer=1024
                    )
                except Exception:
                    pass

            else:
                # Micrófono
                if self.device_index is not None:
                    target_device = self.p.get_device_info_by_index(self.device_index)
                else:
                    target_device = self.p.get_default_input_device_info()

                self.native_rate = int(target_device["defaultSampleRate"])
                self.channels = max(1, target_device["maxInputChannels"])
                self.update_status(f"Capturando micrófono: {target_device['name']}")

            frames_per_buffer = int(self.native_rate * 0.1)  # Bloques de 100 ms

            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.native_rate,
                input=True,
                input_device_index=target_device["index"],
                frames_per_buffer=frames_per_buffer,
                stream_callback=self._audio_callback
            )

            self.stream.start_stream()

            # Bucle de mantenimiento mientras esté activo
            while self.is_running:
                if self.silent_stream and not self.is_paused:
                    try:
                        # Escribir ceros para mantener alimentado el bus de audio
                        self.silent_stream.write(b"\x00" * 1024 * 4, exception_on_underflow=False)
                    except Exception:
                        pass
                time.sleep(0.05)

        except Exception as e:
            self.update_status(f"Error en captura de audio: {e}")
        finally:
            self.stop()
