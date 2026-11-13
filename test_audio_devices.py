"""
Prueba y diagnóstico de dispositivos de audio (WASAPI Loopback y Micrófonos).
"""
import sys

def test_devices():
    print("=== PROBANDO PYAUDIOWPATCH ===")
    try:
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            print(f"[OK] Host API WASAPI detectada: index={wasapi_info['index']}, name={wasapi_info['name']}")
            
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            print(f"[OK] Altavoces por defecto: '{default_speakers['name']}' (Index: {default_speakers['index']})")
            
            # Buscar el dispositivo loopback correspondiente
            loopback_found = False
            for loopback in p.get_loopback_device_info_generator():
                print(f"  -> Dispositivo Loopback: '{loopback['name']}' (Index: {loopback['index']}, Canales: {loopback['maxInputChannels']}, Rate: {int(loopback['defaultSampleRate'])})")
                if default_speakers["name"] in loopback["name"]:
                    print(f"  [★ MATCH] Loopback seleccionado para captura del PC: '{loopback['name']}'")
                    loopback_found = True
            
            if not loopback_found:
                print("  [INFO] No coincidió por nombre exacto, pero hay loopbacks disponibles.")
        except Exception as e:
            print(f"[ERROR] Error al inspeccionar WASAPI: {e}")
        finally:
            p.terminate()
    except Exception as e:
        print(f"[ERROR] No se pudo importar o ejecutar pyaudiowpatch: {e}")

if __name__ == "__main__":
    test_devices()
