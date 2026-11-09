"""Ajustes guardados en config.json (se escriben una sola vez)."""
import os, json

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(BASE, "config.json")
DEFAULT = {
    "backend": "Ollama (local, gratis)",
    "modelo": "qwen2.5:7b",
    "vision_modelo": "qwen2.5vl:7b",
    "api_key": "",
    "hf_token": "",
    "update_url": "https://raw.githubusercontent.com/wallaceperinmancinelli-dot/forgemesh/main",
    "auto_update": True,
}


def cargar():
    cfg = dict(DEFAULT)
    try:
        with open(RUTA, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    for k in ("backend", "modelo", "vision_modelo", "update_url"):  # un valor vacio guardado no debe pisar el default
        if not str(cfg.get(k) or "").strip():
            cfg[k] = DEFAULT[k]
    return cfg


def guardar(**kw):
    cfg = cargar()
    cfg.update({k: v for k, v in kw.items() if k in DEFAULT})
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
    return cfg
