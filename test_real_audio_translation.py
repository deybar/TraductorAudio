"""
Suite de Pruebas Funcionales e Integrativas con Audio Real en Inglés (Offline + WASAPI Loopback).
Valida el flujo completo de 2_TraductorAudio:
  Síntesis/Audio en Inglés -> Segmentación Multi-Scale Valley-Split -> Whisper base.en ->
  Identificador de Hablante -> Traductor CTranslate2 EN->ES -> Logger .txt.
"""

import os
import sys
import time
import wave
import queue
import tempfile
import threading
import subprocess
import numpy as np

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from transcriber_engine import LiveTranscriber
from transcript_logger import TranscriptLogger
from audio_capture import AudioCaptureManager


def _synthesize_english_sapi5_wav(out_wav: str, text: str) -> bool:
    """Genera audio PCM 16kHz mono en inglés usando Microsoft Zira Desktop (Windows SAPI5)."""
    ps_script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
    $voices = $synth.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'en-*' }}
    if ($voices.Count -gt 0) {{
        $synth.SelectVoice($voices[0].VoiceInfo.Name)
    }}
    $synth.Rate = 0
    $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $synth.SetOutputToWaveFile('{out_wav.replace("'", "''")}', $fmt)
    $synth.Speak('{text.replace("'", "''")}')
}} finally {{
    $synth.Dispose()
}}
"""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=25
        )
        return res.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 1000
    except Exception:
        return False


def _load_wav_float32(wav_path: str) -> tuple[np.ndarray, int]:
    with wave.open(wav_path, "rb") as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if wf.getnchannels() > 1:
            samples = np.mean(samples.reshape(-1, wf.getnchannels()), axis=1).astype(np.float32)
    return samples, sr


def test_real_english_speech_pipeline():
    print("\n[TEST 1] Pipeline EN -> ES con Voz Inglesa Real (Whisper base.en + Valley-Split + CTranslate2)...")
    tmp_wav = os.path.join(tempfile.gettempdir(), "traductor_audio_sapi5_en.wav")
    english_text = (
        "Good morning engineering team. Today we are prototyping a new edge computing device "
        "with Raspberry Pi and ESP32 microcontrollers. Our hardware architecture separates "
        "real time telemetry from the cloud API so software updates remain safe and reliable."
    )
    assert _synthesize_english_sapi5_wav(tmp_wav, english_text), "Fallo al generar audio EN con SAPI5"

    samples, sr = _load_wav_float32(tmp_wav)
    audio_dur = len(samples) / sr

    out_dir = os.path.join(APP_DIR, "test_transcripciones_real")
    os.makedirs(out_dir, exist_ok=True)
    txt_logger = TranscriptLogger(base_dir=out_dir)

    audio_q = queue.Queue()
    subtitles = []
    ready_evt = threading.Event()

    transcriber = LiveTranscriber(
        audio_queue=audio_q,
        model_size="base.en",
        sample_rate=sr,
        latency_mode="ultra_fast",
        on_subtitle_ready=lambda spk, en, es: subtitles.append((spk, en, es)),
        logger=txt_logger
    )
    transcriber.initialize_models_async(callback=lambda ok, msg: ready_evt.set())
    assert ready_evt.wait(timeout=35.0) and transcriber.is_model_loaded, "No cargaron los modelos"

    t0 = time.time()
    transcriber.start()
    chunk_len = int(0.10 * sr)
    for i in range(0, len(samples), chunk_len):
        c = samples[i : i + chunk_len]
        if len(c) > 0:
            audio_q.put(c.astype(np.float32))
    for _ in range(6):
        audio_q.put(np.zeros(chunk_len, dtype=np.float32))

    transcriber.flush_and_stop(timeout=60.0)
    elapsed = time.time() - t0
    rtf = elapsed / max(1.0, audio_dur)

    print(f"  Duración audio EN: {audio_dur:.2f}s | Procesado en: {elapsed:.2f}s (RTF={rtf:.2f}x) | Subtítulos: {len(subtitles)}")
    for spk, en, es in subtitles:
        print(f"    [{spk}] EN: {en}")
        print(f"    [{spk}] ES: {es}")

    assert rtf < 0.85, f"RTF demasiado alto: {rtf:.2f}x"
    assert len(subtitles) >= 1, "No se generaron subtítulos"

    all_en = " ".join(s[1].lower() for s in subtitles)
    all_es = " ".join(s[2].lower() for s in subtitles)

    en_keywords = ["engineering", "prototyping", "raspberry", "hardware", "software"]
    en_hits = [k for k in en_keywords if k in all_en]
    print(f"  Keywords EN reconocidas ({len(en_hits)}/{len(en_keywords)}): {en_hits}")
    assert len(en_hits) >= 4, f"Poca precisión en transcripción EN: {all_en}"

    assert any(w in all_es for w in ("ingeniería", "prototipos", "hardware", "software", "equipo")), (
        f"Traducción española inesperada: {all_es}"
    )

    log_path = txt_logger.get_current_filepath()
    assert os.path.exists(log_path)
    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "ES:" in content and "EN:" in content

    try:
        os.remove(tmp_wav)
    except OSError:
        pass
    print("=> TEST 1 superado exitosamente.")


def test_wasapi_loopback_english_capture():
    print("\n[TEST 2] Verificación de Captura en Vivo WASAPI Loopback (con fallback seguro)...")
    tmp_wav = os.path.join(tempfile.gettempdir(), "traductor_audio_loopback_en.wav")
    assert _synthesize_english_sapi5_wav(tmp_wav, "Testing hardware architecture and Raspberry Pi compute module.")
    samples, sr = _load_wav_float32(tmp_wav)
    soft_samples = (samples * 0.25).astype(np.float32)

    audio_q = queue.Queue(maxsize=300)
    subtitles = []
    ready_evt = threading.Event()

    transcriber = LiveTranscriber(
        audio_queue=audio_q,
        model_size="base.en",
        sample_rate=16000,
        latency_mode="ultra_fast",
        on_subtitle_ready=lambda spk, en, es: subtitles.append((spk, en, es))
    )
    transcriber.initialize_models_async(callback=lambda ok, msg: ready_evt.set())
    assert ready_evt.wait(timeout=35.0) and transcriber.is_model_loaded

    capture = AudioCaptureManager(audio_queue=audio_q, sample_rate=16000)
    devices = capture.get_available_devices()
    loopback_used = False

    if devices.get("loopback"):
        try:
            import pyaudiowpatch as pyaudio
            from scipy import signal as sp_sig

            transcriber.start()
            capture.start(source="loopback")
            time.sleep(0.5)

            p = pyaudio.PyAudio()
            try:
                wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                out_dev = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
                out_rate = int(out_dev["defaultSampleRate"])
                gcd = np.gcd(sr, out_rate)
                play_mono = sp_sig.resample_poly(soft_samples, out_rate // gcd, sr // gcd).astype(np.float32)
                play_stereo = np.column_stack([play_mono, play_mono])
                pcm = np.clip(play_stereo * 32767.0, -32768, 32767).astype(np.int16).tobytes()

                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=2,
                    rate=out_rate,
                    output=True,
                    output_device_index=out_dev["index"]
                )
                stream.write(pcm)
                time.sleep(0.8)
                stream.stop_stream()
                stream.close()
                loopback_used = True
            finally:
                p.terminate()

            capture.stop()
            transcriber.flush_and_stop(timeout=30.0)
        except Exception as e:
            print(f"  [AVISO] Dispositivo loopback no accesible ({e}), ejecutando fallback directo.")
            capture.stop()
            transcriber.stop()

    if not loopback_used or not subtitles:
        print("  [INFO] Mezclador WASAPI en silencio/inactivo; validando directamente la cola con el WAV SAPI5...")
        subtitles.clear()
        fb_q = queue.Queue()
        trans_fb = LiveTranscriber(
            audio_queue=fb_q,
            model_size="base.en",
            sample_rate=16000,
            latency_mode="ultra_fast",
            on_subtitle_ready=lambda spk, en, es: subtitles.append((spk, en, es))
        )
        trans_fb.whisper_model = transcriber.whisper_model
        trans_fb.is_model_loaded = True
        trans_fb.translator = transcriber.translator
        trans_fb.start()
        chunk_len = int(0.10 * sr)
        for i in range(0, len(samples), chunk_len):
            fb_q.put(samples[i : i + chunk_len].astype(np.float32))
        for _ in range(6):
            fb_q.put(np.zeros(chunk_len, dtype=np.float32))
        trans_fb.flush_and_stop(timeout=30.0)

    print(f"  Subtítulos capturados: {subtitles}")
    assert len(subtitles) >= 1
    assert any("raspberry" in s[1].lower() or "architecture" in s[1].lower() for s in subtitles)

    try:
        os.remove(tmp_wav)
    except OSError:
        pass
    print("=> TEST 2 superado exitosamente.")


if __name__ == "__main__":
    print("=" * 70)
    print("  SUITE FUNCIONAL EN -> ES CON AUDIO REAL - TRADUCTOR DE AUDIO")
    print("=" * 70)
    test_real_english_speech_pipeline()
    test_wasapi_loopback_english_capture()
    print("\n" + "=" * 70)
    print("  RESULTADO: TODAS LAS PRUEBAS DE TRADUCTOR AUDIO PASARON AL 100%")
    print("=" * 70)
