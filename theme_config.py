"""
Gestión de temas visuales, estilos y persistencia de configuración.
Estilos optimizados para subtítulos cinematográficos flotantes y legibilidad sobre cualquier fondo.
"""

import json
import os
from typing import Dict, Any

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Definición de 5 temas visuales inspirados en 08_TraductorLocal y ajustados para subtítulos
THEMES: Dict[str, Dict[str, str]] = {
    "dark_carbon": {
        "name": "Oscuro Carbón (Cine)",
        "card_bg": "#121214",
        "header_bg": "#1a1a1e",
        "border": "#27272a",
        "text_primary": "#ffffff",
        "text_secondary": "#a1a1aa",
        "text_accent": "#38bdf8",
        "badge_bg": "#1e293b",
        "badge_text": "#38bdf8",
        "speaker_1": "#38bdf8",  # Celeste brillante
        "speaker_2": "#fbbf24",  # Ámbar
        "speaker_3": "#34d399",  # Esmeralda
        "speaker_4": "#f472b6",  # Rosa
        "btn_hover": "#27272a",
        "shadow_color": "rgba(0, 0, 0, 160)"
    },
    "dark_slate": {
        "name": "Oscuro Gris (Grafito)",
        "card_bg": "#1e222b",
        "header_bg": "#252b37",
        "border": "#333b4b",
        "text_primary": "#f8fafc",
        "text_secondary": "#94a3b8",
        "text_accent": "#60a5fa",
        "badge_bg": "#1e293b",
        "badge_text": "#93c5fd",
        "speaker_1": "#60a5fa",
        "speaker_2": "#f59e0b",
        "speaker_3": "#10b981",
        "speaker_4": "#ec4899",
        "btn_hover": "#333b4b",
        "shadow_color": "rgba(0, 0, 0, 140)"
    },
    "dark_mocha": {
        "name": "Oscuro Moca Cálido",
        "card_bg": "#1c1917",
        "header_bg": "#292524",
        "border": "#44403c",
        "text_primary": "#fafaf9",
        "text_secondary": "#a8a29e",
        "text_accent": "#f59e0b",
        "badge_bg": "#292524",
        "badge_text": "#fcd34d",
        "speaker_1": "#fbbf24",
        "speaker_2": "#38bdf8",
        "speaker_3": "#a3e635",
        "speaker_4": "#f43f5e",
        "btn_hover": "#44403c",
        "shadow_color": "rgba(0, 0, 0, 150)"
    },
    "midnight": {
        "name": "Oscuro Noche (Midnight)",
        "card_bg": "#090d16",
        "header_bg": "#0f172a",
        "border": "#1e293b",
        "text_primary": "#f1f5f9",
        "text_secondary": "#64748b",
        "text_accent": "#818cf8",
        "badge_bg": "#1e1b4b",
        "badge_text": "#a5b4fc",
        "speaker_1": "#818cf8",
        "speaker_2": "#38bdf8",
        "speaker_3": "#4ade80",
        "speaker_4": "#f472b6",
        "btn_hover": "#1e293b",
        "shadow_color": "rgba(0, 0, 0, 180)"
    },
    "nord_light": {
        "name": "Claro Suave (Nord)",
        "card_bg": "#f8fafc",
        "header_bg": "#f1f5f9",
        "border": "#cbd5e1",
        "text_primary": "#0f172a",
        "text_secondary": "#64748b",
        "text_accent": "#0284c7",
        "badge_bg": "#e0f2fe",
        "badge_text": "#0369a1",
        "speaker_1": "#0284c7",
        "speaker_2": "#d97706",
        "speaker_3": "#059669",
        "speaker_4": "#be185d",
        "btn_hover": "#e2e8f0",
        "shadow_color": "rgba(0, 0, 0, 60)"
    }
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "theme": "dark_carbon",
    "opacity": 92,
    "font_size": 16,
    "model_size": "base.en",
    "latency_mode": "ultra_fast",  # "ultra_fast" (~1s), "balanced" (~2s), "extended" (~4s)
    "audio_source": "loopback",  # "loopback" o "microphone"
    "audio_device_index": None,
    "display_mode": "bilingual",  # "bilingual", "spanish_only", "english_only"
    "save_transcripts": True,
    "transcripts_dir": "transcripciones",
    "window_pos_x": 200,
    "window_pos_y": 780,
    "window_width": 880,
    "window_height": 160,
    "is_pinned": True,
    "tools_expanded": False
}

def load_config() -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data)
        except Exception:
            pass
    return cfg

def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

def get_theme_data(theme_key: str) -> Dict[str, str]:
    return THEMES.get(theme_key, THEMES["dark_carbon"])
