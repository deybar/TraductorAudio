# 🎧 Traductor de Audio en Tiempo Real (100% Local y Offline) 🔒

> **Versión 1.0.0** — Subtítulos flotantes estilo película en tiempo real, reconocimiento de voz en inglés, traducción instantánea a español y guardado automático con identificación de interlocutores en `.txt`. **100% Privado y ejecutado íntegramente en tu propio ordenador (CPU local).**

---

## 📌 ¿De qué se trata el proyecto y cuál es su propósito?

En reuniones de trabajo (**Microsoft Teams, Google Meet, Zoom**), seminarios web, vídeos técnicos de YouTube o reproducciones de contenido multimedia en inglés, frecuentemente se maneja información sensible, proyectos confidenciales y conversaciones internas de la empresa que **no pueden ni deben ser enviadas a APIs en la nube de terceros** (como Google Cloud Speech, OpenAI Whisper API o DeepL) por motivos estrictos de privacidad corporativa y cumplimiento legal.

Este proyecto resuelve esa necesidad ofreciendo una solución de escritorio con la misma esencia minimalista y fluida de **`08_TraductorLocal`**, pero orientada al canal de audio:
1. **Captura Universal del Sonido del PC (WASAPI Loopback):** Toma el audio que la computadora está reproduciendo en directo, sin necesidad de cables virtuales adicionales.
2. **Transcripción y Traducción Neuronal 100% Local:** Utiliza modelos Whisper optimizados (`faster-whisper` con CTranslate2 e INT8) y traductores neuronales locales (Argos Translate / CTranslate2). **Ningún segundo de audio ni fragmento de texto sale de tu PC hacia internet.**
3. **Popup Flotante Cinematográfico (Subtítulos de Película):** Una ventana emergente traslúcida y elegante que flota sobre cualquier ventana activa con texto nítido, de alto contraste y sombra suave para máxima legibilidad.
4. **Identificación de Interlocutores (Speaker Diarization):** Diferencia acústicamente quién está hablando (`[Hablante 1]`, `[Hablante 2]`, etc.) en tiempo real.
5. **Guardado Automático en `.txt`:** Toda la reunión o vídeo se almacena estructurada y cronológicamente con marcas de tiempo, interlocutor, transcripción en inglés y traducción en español en la carpeta `transcripciones/`.

---

## ✨ Características Principales

- **⚡ Arquitectura de Ultra-Baja Latencia (Tiempo Real Fluido):**
  - **Desacoplamiento Productor-Consumidor:** La captura y segmentación de audio nunca se detiene ni se congela mientras la IA transcribe, evitando retrasos acumulados.
  - **Diarización 150x más Rápida:** Optimización de autocorrelación por ventana espectral que reduce el cálculo de identificación de interlocutores de ~1,500 ms a menos de 10 ms.
  - **Inferencia Instantánea:** Greedy decoding sin cómputo redundante de timestamps en Whisper para CPU local.
  - **Modos de Latencia Seleccionables:**
    - *⚡ Ultra-Rápido (~1s)*: Ideal para conversaciones dinámicas, reuniones ágiles y YouTube.
    - *⚖️ Equilibrado (~2s)*: Ritmo estándar de exposiciones.
    - *📖 Párrafos Largos (~4s)*: Bloques de texto más extensos.
- **🔊 Captura de Audio de Cualquier Origen:** Captura reuniones de Teams, Google Meet, Zoom, vídeos en YouTube, navegadores o cualquier reproductor de Windows.
- **🎙️ Soporte Opcional para Micrófono:** Puedes alternar con un clic entre escuchar el audio que sale del PC o tu propio micrófono.
- **💬 Subtítulos Cinematográficos Flotantes:**
  - Ventana sin bordes (*frameless*) y siempre visible por encima de tus aplicaciones (*Always on Top*).
  - **Barra de Herramientas Colapsable:** Por defecto, los botones se guardan dentro de un discreto icono contenedor (`⚙`). Al hacer clic se expanden todos los controles y al volver a pulsar se ocultan, manteniendo el popup 100% limpio y espacioso.
  - **Indicador Luminoso Minimalista:** Un único punto de estado (`●` verde activo, `●` verde brillante con audio, `●` naranja en pausa) con información en tooltip al pasar el cursor, sin títulos ni textos que resten espacio a los subtítulos.
  - Totalmente arrastrable desde el tirador superior (`⠿`) y redimensionable desde la esquina inferior (`⤡`).
  - Control de opacidad/transparencia regulable (desde 75% hasta 100%).
  - Tres modos de visualización: **Bilingüe** (Español + Inglés), **Solo Español** o **Solo Inglés**.
  - Ajuste de tamaño de fuente al instante (`A-` / `A+`).
  - **➕ Nueva Sesión Instantánea:** Botón para iniciar una nueva reunión o sesión que abre un nuevo archivo `.txt` limpio y reinicia los interlocutores. El botón `⏸` permite pausar y reanudar sobre el mismo archivo.
- **👥 Identificación Inteligente de Interlocutores:** Análisis espectral y de tono vocal en CPU para etiquetar las intervenciones de cada participante con colores distintivos.
- **📝 Registro Automático en Texto Plano (`.txt`):** Cada sesión genera un archivo con formato:
  ```text
  [14:50:12] [Hablante 1]
  EN: Good afternoon everyone, let's start the review of project budget.
  ES: Buenas tardes a todos, comencemos la revisión del presupuesto del proyecto.
  ```
  Acceso directo al archivo actual (`📄 .txt`) o a la carpeta de grabaciones desde la barra de herramientas.
- **🎨 5 Temas Visuales:**
  - *Oscuro Carbón (Cine)*: Minimalista de alto contraste cinematográfico.
  - *Oscuro Gris (Grafito)*: Tonos pizarra sobrios.
  - *Oscuro Moca Cálido*: Fondo marrón oscuro con acentos cálidos ámbar.
  - *Oscuro Noche (Midnight)*: Azul marino profundo.
  - *Claro Suave (Nord)*: Paleta clara para ambientes iluminados.
- **🛡️ Single Instance Guard:** Si ejecutas el programa cuando ya está abierto, no se duplican procesos; la ventana existente se restaura y se enfoca de inmediato.
- **🤫 Ejecución Silenciosa en Segundo Plano:** El lanzador `iniciar.vbs` abre la aplicación sin ventanas negras de consola CMD.

---

## 🛠️ Herramientas y Tecnologías Utilizadas

| Componente | Tecnología | Descripción |
|---|---|---|
| **Lenguaje** | Python 3.11+ | Lenguaje base del proyecto |
| **Interfaz de Usuario (GUI)** | PyQt6 (Qt 6) | Ventanas flotantes sin bordes, transparencias nativas, widgets CSS y bandeja del sistema |
| **Captura de Audio Interno** | `pyaudiowpatch` | Captura directa WASAPI Loopback del canal de altavoces/auriculares en Windows sin cables virtuales |
| **Reconocimiento de Voz (ASR)** | `faster-whisper` | Motor de inferencia CTranslate2 con cuantización INT8 y filtrado VAD (Silero) para CPU local |
| **Motor de Traducción (MT)** | Argos Translate / CTranslate2 | Modelos neuronales OpenNMT de alto rendimiento especializados en pares Inglés ➔ Español |
| **Diarización de Hablantes** | Algoritmo acústico local (FFT + F0 + Bandas) | Extracción de huellas vocales y agrupamiento dinámico en CPU |
| **Procesamiento de Señal** | `numpy` & `scipy.signal` | Remuestreo polifásico en tiempo real a 16 kHz mono |
| **Lanzadores y Accesos** | VBScript & Batch | Inicio 100% silencioso y modo de depuración en consola |

---

## 🚀 Cómo Ejecutar el Programa

### Opción 1: Ejecución Rápida (Para usuarios finales)
Haz doble clic en los archivos de inicio incluidos en la raíz del proyecto:
- **`iniciar.vbs`** *(Recomendado)*: Inicia el traductor de forma **100% silenciosa** en segundo plano (sin ventana negra de CMD).
- **`iniciar.bat`**: Lanzador por lotes alternativo.
- **`debug_consola.bat`**: Abre la aplicación mostrando los registros de consola en vivo para diagnóstico y pruebas.

### Opción 2: Instalación y Ejecución para Desarrolladores
1. **Crear el entorno virtual (recomendado en `C:\Users\%USERNAME%\.audio_translator_venv` para máximo rendimiento de disco):**
   ```bash
   uv venv C:\Users\%USERNAME%\.audio_translator_venv --python 3.11
   ```

2. **Instalar dependencias:**
   ```bash
   uv pip install --python C:\Users\%USERNAME%\.audio_translator_venv\Scripts\python.exe -r requirements.txt
   ```

3. **Ejecutar la aplicación:**
   ```bash
   C:\Users\%USERNAME%\.audio_translator_venv\Scripts\python.exe main.py
   ```

---

## 📂 Estructura del Código

```text
09_TraductorAudio/
├── main.py                 # Orquestador principal, bandeja del sistema y Single Instance Guard
├── audio_capture.py        # Capturador de audio en vivo (WASAPI Loopback para PC y Micrófono)
├── transcriber_engine.py   # Motor de transcripción en tiempo real con Faster-Whisper
├── translator_engine.py    # Motor de traducción instantánea CTranslate2 (Inglés -> Español)
├── speaker_engine.py       # Identificador de interlocutores y extracción de huella acústica
├── subtitle_window.py      # Ventana flotante estilo película (arrastrable, redimensionable)
├── transcript_logger.py    # Gestor de guardado automático de transcripciones en .txt
├── theme_config.py         # Paleta de 5 temas, configuración y estilos visuales
├── config.json             # Archivo de configuración persistente
├── requirements.txt        # Lista de dependencias del proyecto
├── test_audio_devices.py   # Diagnóstico de dispositivos WASAPI Loopback y micrófonos
├── test_full_pipeline.py   # Prueba integral de consola del pipeline completo
├── iniciar.vbs             # Lanzador 100% silencioso sin consola
├── iniciar.bat             # Lanzador por lotes estándar
├── debug_consola.bat       # Lanzador con ventana de depuración activa
├── .gitignore              # Exclusiones de Git
└── transcripciones/        # Directorio donde se guardan las sesiones en .txt
```

---

## 🔒 Privacidad y Seguridad

- **Cero telemetría:** La aplicación no se comunica con ningún servidor externo durante su funcionamiento.
- **Seguridad corporativa:** Todas las conversaciones de Teams, Meet o vídeos procesados se mantienen de forma estricta y exclusiva en la memoria RAM y el disco local de tu equipo.
