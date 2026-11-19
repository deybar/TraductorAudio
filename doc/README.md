# 📚 Documentación Técnica del Traductor de Audio en Tiempo Real

Bienvenido a la documentación técnica de **Traductor de Audio en Tiempo Real (`09_TraductorAudio`)**, integrante de la **Suite de Productividad e IA Local**.

---

## 🗂️ Índice de Contenidos

1. [**01. Arquitectura y Flujo de Procesamiento**](file:///G:/Mi%20unidad/08_Programas%20PC/09_TraductorAudio/doc/01_arquitectura_y_flujo.md)
   - Pipeline de audio: captura WASAPI Loopback, remuestreo, Silero VAD, Faster-Whisper, CTranslate2 y renderizado de subtítulos.
2. [**02. Protocolo IPC y Almacenamiento de Datos**](file:///G:/Mi%20unidad/08_Programas%20PC/09_TraductorAudio/doc/02_protocolo_ipc_y_datos.md)
   - Control de instancia única con `TraductorAudio_SingleInstance_2026`, formato de logs en `transcripciones/` y roadmap hacia el estándar tri-formato.
3. [**03. Guía de Uso y Configuración**](file:///G:/Mi%20unidad/08_Programas%20PC/09_TraductorAudio/doc/03_guia_de_uso_y_atajos.md)
   - Modos de subtitulado (bilingüe, solo español, solo inglés), selección de dispositivos de salida, latencia y personalización visual.
4. [**04. Integración en el Macro-Sistema**](file:///G:/Mi%20unidad/08_Programas%20PC/09_TraductorAudio/doc/04_integracion_macro_sistema.md)
   - Relación con el Lanzador `12_Lanzador-Apps-IA`, sinergia con `10_Asistente-de-reunion` y preparación para el frontend unificado.
