# 📡 02. Protocolo IPC y Almacenamiento de Datos

Este documento describe el canal de control de instancia única (IPC), la estructura de persistencia en `config.json` y el almacenamiento de sesiones de **Traductor de Audio en Tiempo Real**.

---

## 1. Control de Instancia Única vía Named Pipes

El programa previene múltiples procesos concurrentes usando el servidor local de sockets de Qt:
- **Identificador de Socket:** `TraductorAudio_SingleInstance_2026`
- **Mecanismo:**
  1. Al iniciar, intenta conectarse al socket existente.
  2. Si responde, envía `b"ACTIVATE"`, lo que provoca que la ventana existente se restaure y se posicione en primer plano.
  3. Si no responde, asume el rol maestro e inicia la escucha para responder a peticiones futuras del lanzador `12_Lanzador-Apps-IA`.

---

## 2. Configuración Persistente (`config.json`)

Los parámetros del usuario se guardan en la raíz del proyecto en `config.json`:

```json
{
  "theme": "dark_carbon",
  "font_size": 14,
  "opacity": 0.92,
  "model_size": "tiny.en",
  "latency_mode": "ultra_fast",
  "audio_source": "loopback",
  "audio_device_index": null,
  "display_mode": "bilingual",
  "save_transcripts": true,
  "transcripts_dir": "transcripciones",
  "window_pos_x": 0,
  "window_pos_y": 0,
  "window_width": 780,
  "window_height": 130
}
```

### Campos Clave:
- `latency_mode`: Controla la ventana de procesamiento (`ultra_fast` ~ 1.5s, `balanced` ~ 3.0s, `high_accuracy` ~ 5.0s).
- `display_mode`: Define el formato en pantalla (`bilingual`, `spanish_only`, `english_only`).
- `window_pos_x` / `window_pos_y`: Recuerda la última posición en pantalla donde el usuario ubicó la barra de subtítulos.

---

## 3. Registro de Transcripciones y Hoja de Ruta al Estándar Tri-Formato

Actualmente las sesiones se almacenan en `transcripciones/transcripcion_YYYYMMDD_HHMMSS.txt`:
```text
[14:50:48] [Hablante 1] (EN): Good morning team, let's review our private internal quarterly targets.
[14:50:48] [Hablante 1] (ES): Buen equipo de mañana, revisemos nuestros objetivos trimestrales internos privados.
```

### 🎯 Evolución hacia el Estándar Tri-Formato (Fase 2):
Siguiendo el diseño implementado en `10_Asistente-de-reunion`, la Fase 2 incorporará:
1. **Audio Maestro (`.wav`):** Grabación directa a disco del stream de audio en 16 kHz mono.
2. **Minuta Bilingüe (`.md`):** Archivo Markdown con Frontmatter YAML y tablas par a par Inglés / Español.
3. **Timeline para Frontend (`.json`):** Arreglo de segmentos con marcas `{start_sec, end_sec, en_text, es_text, speaker}` para reproductores con *click-to-seek*.
