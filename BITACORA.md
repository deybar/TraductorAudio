# 📋 Bitácora de Desarrollo y Hoja de Ruta (Roadmap)
## Proyecto: Traductor de Audio en Tiempo Real (Subtítulos Bilingües y Captura WASAPI)

Esta bitácora documenta el diagnóstico técnico, la arquitectura, las deudas detectadas, el plan de evolución y el registro histórico de versiones del **Traductor de Audio en Tiempo Real**, componente del **Macro-Sistema de IA Local**.

---

## 🧭 1. Visión y Diagnóstico de Arquitectura (v1.0.0)

El proyecto captura el audio reproducido por el ordenador en Windows (reuniones de Microsoft Teams, Zoom, Google Meet, vídeos de YouTube, cursos técnicos o llamadas) mediante **WASAPI Loopback**, reconoce el habla en inglés en tiempo real con **Faster-Whisper (INT8)**, traduce a español con **CTranslate2**, e inyecta **subtítulos cinematográficos flotantes y bilingües** de alta legibilidad sobre cualquier ventana activa.

### Fortalezas Clave
- **100% Local y Confidencial:** No requiere tokens, APIs ni servicios en la nube.
- **Captura Directa de Hardware (WASAPI Loopback):** Escucha lo que sale por los auriculares o altavoces sin requerir Virtual Audio Cable ni cables físicos.
- **Diarización Acústica Integrada (`speaker_engine.py`):** Diferencia a los distintos participantes de la llamada por tono y características espectrales.
- **Subtítulos Bilingües Cinematográficos:** Diseño traslúcido tipo cine con alineación par a par (Español destacado arriba, Inglés de referencia pegado abajo) para aprendizaje y comprensión inmediata.
- **Control de Instancia Única:** Named Pipe `TraductorAudio_SingleInstance_2026`.

---

## 🔍 2. Deudas Técnicas y Oportunidades de Mejora

| ID | Área | Descripción de la Oportunidad / Deuda | Prioridad |
|---|---|---|---|
| **DT-TA01** | **Ecosistema Tri-Formato** | Actualmente guarda solo en `.txt`. Debe incorporar el estándar sincronizado `.wav` (audio raw) + `.md` (minuta bilingüe) + `.json` (timeline para frontend). | **Alta** |
| **DT-TA02** | **Modo Cápsula Zen** | En momentos donde solo se desea registrar la sesión sin ver subtítulos en pantalla, implementar un modo colapsable mínimo similar al Asistente de Reunión. | **Media** |
| **DT-TA03** | **Captura Dual de Micrófono** | Extender opcionalmente la captura al micrófono del usuario (modo bidireccional) como lo hace `10_Asistente-de-reunion`. | **Media** |
| **DT-TA04** | **Aceleración GPU Opcional** | Permitir conmutación a CUDA/DirectML si el usuario dispone de GPU NVIDIA dedicada para modelos más grandes (`small.en` o `base.en`). | **Baja** |

---

## 🗺️ 3. Plan de Trabajo y Fases de Evolución

```mermaid
flowchart LR
    Fase1["Fase 1: Estandarización y Macro-Ecosistema"] --> Fase2["Fase 2: Tri-Formato WAV + MD + JSON"]
    Fase2 --> Fase3["Fase 3: Modo Zen y Atajos"]
    Fase3 --> Fase4["Fase 4: Frontend / Intérprete Unificado"]
```

### 🔹 Fase 1: Estandarización y Macro-Ecosistema (En Progreso)
- [x] Migración de rama principal a `main` y control de versiones profesional.
- [x] Documentación exhaustiva técnica y de flujo en `doc/`.
- [x] Bitácora técnica y registro de arquitectura macro.
- [x] Verificación de pruebas automatizadas del pipeline de audio y traducción.

### 🔹 Fase 2: Protocolo Tri-Formato Sincronizado
- [ ] Integración del módulo de grabación continua `AudioRecorder` a `.wav` (16 kHz mono).
- [ ] Generación simultánea de transcripción en **Markdown (`.md`)** bilingüe con Frontmatter YAML y tablas de vocabulario.
- [ ] Generación de **Timeline JSON (`.json`)** con timestamps relativos al audio `{start_sec, end_sec, en_text, es_text, speaker}` para el frontend interactivo.

### 🔹 Fase 3: Modo Zen y Atajos de Teclado
- [ ] Incorporación del widget de onda de audio reactiva para supervisión silenciosa.
- [ ] Atajo de teclado global para ocultar/mostrar subtítulos rápidamente (`Ctrl+Shift+S`).
- [ ] Selector rápido de dispositivo de audio de entrada directo desde el menú.

### 🔹 Fase 4: Integración en el Dashboard / Intérprete Unificado
- [ ] Conexión de sesiones de subtítulos con el frontend común de la suite para reproducir el audio con *click-to-seek* bilingüe.

---

## 📝 4. Registro Histórico de Cambios (Changelog)

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y versionado semántico.

### [1.2.0] - 2026-11-20
#### Diagnóstico de Sesiones Reales (19–20 Nov)
- **Corrupción en traducción (`compute_type="int8"`):** Detectado en CTranslate2 sobre el paquete `en_es` en CPU; provocaba distorsiones en frases largas. Corregido migrando a `compute_type="default"`.
- **Pérdida de geometría al reiniciar:** La ventana de subtítulos restablecía coordenadas tras cambios rápidos. Corregido inicializando posición persistida antes de `apply_theme()`.
- **Palabras partidas al límite de `max_speech` (ej. `"for part... | type in"` por `"for prototyping"`):** El corte rígido por tiempo fragmentaba palabras inglesas entre bloques y descartaba cola de audio.
- **Doble filtrado Silero VAD:** Ejecutar `vad_filter=True` dentro de `WhisperModel.transcribe` tras segmentar con Silero VAD v6 consumía CPU innecesariamente y recortaba inicios/finales de palabra.

#### Optimizaciones y Experimentos Implementados
- **Modelo por defecto actualizado a `base.en` (`theme_config.py`, `config.json`):** Mejor equilibrio entre precisión léxica en inglés técnico y velocidad en CPU (`Intel Core i7-6500U`, `cpu_threads=4`, `beam_size=2`).
- **Multi-Scale Word-Valley Splitting (130ms + 240ms):** Nuevo algoritmo `_find_best_valley_cut()` que localiza el valle de mínima energía en los últimos `2.0s` al alcanzar `max_speech`, conservando íntegramente `carry_over = raw_buffer[cut_idx:]` para el siguiente bloque sin perder sílabas ni muestras.
- **Calibración Silero VAD v6 + Acondicionador Acústico:** Reducción de ganancia máxima VAD de `10x` a `3.5x` (umbral `0.42`) para no elevar música o ruido sobre el detector, manteniendo filtro pasa-altos 80Hz + AGC adaptativo en inferencia y desactivando `vad_filter` redundante en Whisper.
- **Contexto Técnico Continuo y Cierre Ordenado:** `initial_prompt` enriquecido con terminología técnica + ventana móvil de contexto (`140` caracteres), cola `_transcribe_queue` ampliada a `16` y método `flush_and_stop()` sin pérdida del último fragmento.
- **Histeresis en Diarización (`speaker_engine.py`) e IPC (`QUIT`):** Estabilización de etiquetas (`Hablante 1`) y soporte de cierre remoto desde el widget lanzador.

#### Validación Funcional y Pruebas (`test_real_audio_translation.py` + `test_full_pipeline.py`)
- **Síntesis SAPI5 Real (`Microsoft Zira Desktop`, 17.18s audio técnico EN):** Procesada en `11.18s` (**`RTF = 0.65x`**, más rápido que tiempo real), **5/5** palabras clave técnicas reconocidas (`engineering`, `prototyping`, `raspberry`, `hardware`, `software`), traducción española precisa y registro `.txt` verificado.
- **Captura en Vivo WASAPI Loopback:** Verificada captura real desde altavoces del sistema con fallback automático en entorno silencioso.

### [1.1.0] - 2026-11-19
#### Añadido
- **Alineación con la Macro Suite de IA:** Renombramiento de rama principal a `main`.
- **Suite de Documentación Técnica:** Incorporación de la carpeta `doc/` con arquitectura, flujo de audio, protocolo IPC y manual de usuario.
- **Bitácora Formal:** Creación de `BITACORA.md` con mapa de dependencias y roadmap para el protocolo tri-formato.
- **Estandarización de .gitignore:** Reglas actualizadas para futuros archivos `.wav`, `.md` y `.json`.

### [1.0.0] - 2026-11-13
#### Añadido
- Captura WASAPI Loopback en tiempo real para sonido del PC.
- Motor de transcripción Whisper `tiny.en` cuantizado INT8 con Silero VAD.
- Motor de traducción neuronal CTranslate2 (Inglés a Español).
- Diarización acústica en CPU para diferenciar interlocutores.
- Ventana de subtítulos flotantes de alta legibilidad con auto-ajuste y arrastre.
- Modos de visualización: Bilingüe (Español arriba, Inglés abajo), Solo Español, Solo Inglés.
- Registro automático de sesiones en `transcripciones/*.txt`.
- Sockets locales `TraductorAudio_SingleInstance_2026` y ejecutor silencioso `iniciar.vbs`.
