"""
Motor de Identificación de Interlocutores (Speaker Diarization / Clustering) 100% Local.
Analiza huellas acústicas espectrales (pitch, centroide espectral, cruces por cero y bancos de frecuencia)
para diferenciar a los participantes de la conversación (Hablante 1, Hablante 2, etc.) en tiempo real en CPU.
"""

import numpy as np
from typing import List, Dict, Optional

class SpeakerIdentifier:
    def __init__(self, max_speakers: int = 8, similarity_threshold: float = 0.70):
        self.max_speakers = max_speakers
        self.similarity_threshold = similarity_threshold
        # Perfiles de hablantes: {speaker_id: {"name": str, "centroid": np.ndarray, "count": int}}
        self.speakers: Dict[int, Dict] = {}
        self.last_speaker_id: int = 1
        self.next_speaker_id: int = 1
        self._divergent_streak: int = 0

    def reset(self):
        """Reinicia la lista de interlocutores para una nueva sesión."""
        self.speakers.clear()
        self.last_speaker_id = 1
        self.next_speaker_id = 1
        self._divergent_streak = 0

    def extract_voiceprint(self, audio: np.ndarray, sample_rate: int = 16000) -> Optional[np.ndarray]:
        """
        Extrae un vector de características acústicas (huella vocal normalizada).
        """
        if len(audio) < sample_rate * 0.4:
            # Segmento demasiado corto para extraer huella fiable
            return None

        # Asegurar float32 y eliminar offset DC
        samples = audio.astype(np.float32)
        samples = samples - np.mean(samples)
        rms = np.sqrt(np.mean(samples ** 2))
        if rms < 1e-4:
            return None  # Silencio

        # Limitar análisis a un segmento representativo si el audio es extenso
        if len(samples) > 24000:
            analysis_samples = samples[:24000]
        else:
            analysis_samples = samples

        # 1. Tasa de cruces por cero (Zero-crossing rate)
        zero_crossings = np.sum(np.abs(np.diff(np.sign(analysis_samples)))) / (2 * len(analysis_samples))

        # 2. Espectro de Fourier (FFT)
        fft_vals = np.abs(np.fft.rfft(analysis_samples * np.hamming(len(analysis_samples))))
        freqs = np.fft.rfftfreq(len(analysis_samples), 1.0 / sample_rate)
        
        sum_fft = np.sum(fft_vals) + 1e-8
        
        # 3. Centroide espectral (brillo de la voz)
        spectral_centroid = np.sum(freqs * fft_vals) / sum_fft
        
        # 4. Dispersión espectral (ancho de banda)
        spectral_spread = np.sqrt(np.sum(((freqs - spectral_centroid) ** 2) * fft_vals) / sum_fft)
        
        # 5. Rolloff espectral (frecuencia bajo la cual está el 85% de la energía)
        cumulative_energy = np.cumsum(fft_vals)
        rolloff_idx = np.searchsorted(cumulative_energy, 0.85 * cumulative_energy[-1])
        spectral_rolloff = freqs[min(rolloff_idx, len(freqs) - 1)]

        # 6. Estimación optimizada de F0 (Pitch) por autocorrelación de ventana rápida
        # Ventana de 2048 muestras (~128 ms): reduce tiempo de correlación de 1500ms a 1ms
        if len(samples) > 2048:
            mid = len(samples) // 2
            pitch_samples = samples[mid - 1024 : mid + 1024]
        else:
            pitch_samples = samples

        corr = np.correlate(pitch_samples, pitch_samples, mode='full')
        corr = corr[len(corr)//2:]
        # Rango vocal humano: 60 Hz a 400 Hz
        min_lag = int(sample_rate / 400)
        max_lag = int(sample_rate / 60)
        if len(corr) > max_lag:
            pitch_lag = min_lag + np.argmax(corr[min_lag:max_lag])
            f0_estimate = sample_rate / max(1, pitch_lag)
        else:
            f0_estimate = 150.0

        # 7. Energías por bandas de frecuencia (8 bandas críticas de voz humana: 100Hz - 4000Hz)
        band_edges = [100, 300, 600, 1000, 1500, 2200, 3000, 4500, 7000]
        band_energies = []
        for i in range(len(band_edges) - 1):
            mask = (freqs >= band_edges[i]) & (freqs < band_edges[i+1])
            energy = np.sum(fft_vals[mask]) / sum_fft if np.any(mask) else 0.0
            band_energies.append(energy)

        # Construir vector de características
        features = np.array([
            zero_crossings * 10.0,
            spectral_centroid / 2000.0,
            spectral_spread / 1500.0,
            spectral_rolloff / 3000.0,
            f0_estimate / 200.0
        ] + [e * 5.0 for e in band_energies], dtype=np.float32)

        # Normalizar vector a norma unitaria (L2)
        norm = np.linalg.norm(features)
        if norm > 1e-6:
            features = features / norm
        return features

    def identify_speaker(self, audio: np.ndarray, sample_rate: int = 16000, pause_duration: float = 0.0) -> str:
        """
        Determina a qué interlocutor corresponde el segmento de audio.
        Retorna la etiqueta del hablante (ej: "Hablante 1", "Hablante 2").
        """
        voiceprint = self.extract_voiceprint(audio, sample_rate)

        # Si el audio es muy corto y no hubo una pausa larga, asumir el hablante anterior
        if voiceprint is None:
            if pause_duration < 1.2 and self.speakers:
                return self.speakers[self.last_speaker_id]["name"]
            return f"Hablante {self.last_speaker_id}"

        # Si no hay hablantes registrados aún, registrar el primero
        if not self.speakers:
            self.speakers[1] = {
                "name": "Hablante 1",
                "centroid": voiceprint,
                "count": 1
            }
            self.last_speaker_id = 1
            self.next_speaker_id = 2
            return "Hablante 1"

        # Comparar con los hablantes registrados usando similitud coseno
        best_speaker_id = None
        best_similarity = -1.0

        for spk_id, spk_data in self.speakers.items():
            sim = float(np.dot(voiceprint, spk_data["centroid"]))
            if sim > best_similarity:
                best_similarity = sim
                best_speaker_id = spk_id

        # Si coincide suficientemente con un hablante conocido
        if best_similarity >= self.similarity_threshold and best_speaker_id is not None:
            # Actualizar centroide del hablante de forma adaptativa (promedio móvil)
            spk = self.speakers[best_speaker_id]
            alpha = min(0.2, 1.0 / (spk["count"] + 1))
            new_centroid = (1.0 - alpha) * spk["centroid"] + alpha * voiceprint
            new_norm = np.linalg.norm(new_centroid)
            if new_norm > 1e-6:
                spk["centroid"] = new_centroid / new_norm
            spk["count"] += 1
            self.last_speaker_id = best_speaker_id
            self._divergent_streak = 0
            return spk["name"]

        # Histeresis para evitar fragmentar a un mismo hablante en variaciones tonales leves
        self._divergent_streak += 1
        clear_change = (best_similarity < 0.55) or (
            len(audio) >= sample_rate * 1.2 and pause_duration >= 0.8 and self._divergent_streak >= 2
        )
        if not clear_change:
            return self.speakers[self.last_speaker_id]["name"]

        self._divergent_streak = 0

        # Si no coincide y aún podemos crear un nuevo hablante
        if len(self.speakers) < self.max_speakers:
            new_id = self.next_speaker_id
            self.next_speaker_id += 1
            name = f"Hablante {new_id}"
            self.speakers[new_id] = {
                "name": name,
                "centroid": voiceprint,
                "count": 1
            }
            self.last_speaker_id = new_id
            return name
        else:
            # Si se alcanzó el máximo, asignar al más parecido
            self.last_speaker_id = best_speaker_id if best_speaker_id else 1
            return self.speakers[self.last_speaker_id]["name"]
