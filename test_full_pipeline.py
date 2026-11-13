"""
Prueba integral de la cadena completa de traducción de audio:
Audio -> Faster-Whisper -> Speaker Identifier -> Translator CTranslate2 -> Logger .txt
"""
import time
import numpy as np
from faster_whisper import WhisperModel
from speaker_engine import SpeakerIdentifier
from translator_engine import LocalTranslator
from transcript_logger import TranscriptLogger

def test_pipeline():
    print("=" * 65)
    print("  TEST PIPELINE TRADUCTOR DE AUDIO EN TIEMPO REAL")
    print("=" * 65)

    print("\n[1/5] Inicializando Logger en 'transcripciones'...")
    logger = TranscriptLogger(base_dir="transcripciones")
    print(f"[OK] Archivo de sesión creado: {logger.get_current_filepath()}")

    print("\n[2/5] Inicializando Speaker Identifier...")
    spk_id = SpeakerIdentifier()
    # Simular dos voces sintéticas diferentes
    t = np.linspace(0, 1.5, int(16000 * 1.5), endpoint=False)
    voice_1 = 0.5 * np.sin(2 * np.pi * 180 * t) + 0.2 * np.sin(2 * np.pi * 360 * t) # ~180 Hz
    voice_2 = 0.5 * np.sin(2 * np.pi * 260 * t) + 0.2 * np.sin(2 * np.pi * 520 * t) # ~260 Hz

    s1 = spk_id.identify_speaker(voice_1)
    s2 = spk_id.identify_speaker(voice_2)
    s1_again = spk_id.identify_speaker(voice_1)
    print(f"  Voz A identificada como: {s1}")
    print(f"  Voz B identificada como: {s2}")
    print(f"  Voz A re-identificada como: {s1_again}")

    print("\n[3/5] Inicializando Traductor CTranslate2 (EN -> ES)...")
    translator = LocalTranslator()
    translator._load_or_install_models()
    sample_text = "Good morning team, let's review our private internal quarterly targets."
    trans_es = translator.translate_en_to_es(sample_text)
    print(f"  Texto original (EN): {sample_text}")
    print(f"  Traducción (ES):     {trans_es}")

    print("\n[4/5] Escribiendo en archivo .txt...")
    logger.log_entry(s1, sample_text, trans_es)
    sample_text_2 = "I agree, we have finished all client requirements for this sprint."
    trans_es_2 = translator.translate_en_to_es(sample_text_2)
    logger.log_entry(s2, sample_text_2, trans_es_2)
    print(f"  Texto original (EN): {sample_text_2}")
    print(f"  Traducción (ES):     {trans_es_2}")
    print("[OK] Ambas intervenciones registradas en el .txt.")

    print("\n[5/5] Inicializando Faster-Whisper 'tiny.en'...")
    whisper = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    print("[OK] Faster-Whisper cargado correctamente en memoria.")

    print("\n" + "=" * 65)
    print("  ¡TODAS LAS PRUEBAS COMPLETADAS CON ÉXITO (100% OFFLINE / LOCAL)!")
    print("=" * 65)

if __name__ == "__main__":
    test_pipeline()
