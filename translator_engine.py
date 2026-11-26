"""
Motor de Traducción 100% Local y Offline (Inglés -> Español).
Carga directa de modelos CTranslate2 (INT8) + SentencePiece desde disco
para inferencia ultrarrápida sin cargar librerías pesadas en arranque.
"""

import os
import json
import threading
from pathlib import Path
from typing import Optional, Callable, List
import ctranslate2
import sentencepiece as spm


class _FastSentencePieceTokenizer:
    """Tokenizador SentencePiece ligero sin dependencias externas."""
    def __init__(self, model_file: Path):
        self.processor = spm.SentencePieceProcessor(model_file=str(model_file))

    def encode(self, sentence: str) -> List[str]:
        return self.processor.encode(sentence, out_type=str)

    def decode(self, tokens: List[str]) -> str:
        return (
            self.processor.decode_pieces(tokens)
            .replace("▁", " ")
            .replace("_", " ")
        )


def _find_en_es_pkg_dir() -> Optional[Path]:
    """Localiza el directorio del paquete EN->ES en disco."""
    search_roots = []
    local_app = os.environ.get("LOCALAPPDATA")
    app_data = os.environ.get("APPDATA")
    user_home = os.path.expanduser("~")

    if local_app:
        search_roots.append(Path(local_app) / "argos-translate" / "packages")
    search_roots.append(Path(user_home) / ".local" / "share" / "argos-translate" / "packages")
    if app_data:
        search_roots.append(Path(app_data) / "argos-translate" / "packages")

    for root in search_roots:
        if not root.is_dir():
            continue
        for pkg_dir in root.iterdir():
            if not pkg_dir.is_dir() or not (pkg_dir / "model").is_dir():
                continue

            from_code, to_code = None, None
            meta_file = pkg_dir / "metadata.json"
            if meta_file.is_file():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    from_code = meta.get("from_code")
                    to_code = meta.get("to_code")
                except Exception:
                    pass

            if not (from_code and to_code) and "en_es" in pkg_dir.name.lower():
                from_code, to_code = "en", "es"

            if from_code == "en" and to_code == "es":
                if (pkg_dir / "sentencepiece.model").is_file() or (pkg_dir / "bpe.model").is_file():
                    return pkg_dir
    return None


class LocalTranslator:
    def __init__(self, on_status_changed: Optional[Callable[[str], None]] = None):
        self.on_status_changed = on_status_changed
        self.is_ready = False
        self.is_loading = False

        self._en_es_tokenizer = None
        self._en_es_translator = None
        self._lock = threading.Lock()

    def update_status(self, msg: str):
        if self.on_status_changed:
            self.on_status_changed(msg)

    def initialize_models_async(self, callback: Optional[Callable[[bool, str], None]] = None):
        """Inicializa los modelos en segundo plano sin bloquear el hilo principal."""
        thread = threading.Thread(target=self._load_or_install_models, args=(callback,), daemon=True)
        thread.start()

    def _load_or_install_models(self, callback: Optional[Callable[[bool, str], None]] = None):
        with self._lock:
            if self.is_ready:
                if callback:
                    callback(True, "Modelo de traducción ya listo")
                return

            self.is_loading = True
            try:
                self.update_status("Buscando paquetes locales de traducción EN -> ES...")
                pkg_dir = _find_en_es_pkg_dir()

                # Si no está instalado en disco, importar argostranslate.package como fallback
                if not pkg_dir:
                    import argostranslate.package
                    self.update_status("Descargando paquete de traducción local EN -> ES (~45MB)...")
                    argostranslate.package.update_package_index()
                    available_packages = argostranslate.package.get_available_packages()
                    for pkg in available_packages:
                        if pkg.from_code == "en" and pkg.to_code == "es":
                            download_path = pkg.download()
                            argostranslate.package.install_from_path(download_path)
                            break
                    pkg_dir = _find_en_es_pkg_dir()

                if pkg_dir:
                    self.update_status("Cargando motor CTranslate2 de traducción en CPU...")
                    sp_path = pkg_dir / "sentencepiece.model"
                    bpe_path = pkg_dir / "bpe.model"
                    if sp_path.is_file():
                        self._en_es_tokenizer = _FastSentencePieceTokenizer(sp_path)
                    elif bpe_path.is_file():
                        from argostranslate.tokenizer import BPETokenizer
                        self._en_es_tokenizer = BPETokenizer(bpe_path, "en", "es")

                    model_path = str(pkg_dir / "model")
                    self._en_es_translator = ctranslate2.Translator(
                        model_path,
                        device="cpu",
                        compute_type="default"
                    )
                    if self._en_es_tokenizer:
                        self.is_ready = True
                        self.is_loading = False
                        self.update_status("Traductor local listo (100% Offline)")
                        if callback:
                            callback(True, "Traductor cargado exitosamente")
                        return

                self.is_ready = False
                self.is_loading = False
                err = "No se pudo localizar el paquete EN->ES de Argos Translate."
                self.update_status(err)
                if callback:
                    callback(False, err)

            except Exception as e:
                self.is_ready = False
                self.is_loading = False
                err = f"Error al inicializar traductor: {str(e)}"
                self.update_status(err)
                if callback:
                    callback(False, err)

    def translate_en_to_es(self, text: str) -> str:
        """
        Traduce una frase de inglés a español de manera inmediata usando CTranslate2.
        Retorna el texto traducido en español.
        """
        if not text or not text.strip():
            return ""

        clean_text = text.strip()

        if not self.is_ready:
            self._load_or_install_models()
            if not self.is_ready:
                return clean_text

        try:
            tokens = self._en_es_tokenizer.encode(clean_text)
            result = self._en_es_translator.translate_batch([tokens], beam_size=2)
            hyp = result[0].hypotheses[0]
            translated = self._en_es_tokenizer.decode(hyp)
            return translated.strip()
        except Exception:
            return clean_text
