"""Interpreta muchas fotos/ilustraciones de un mismo objeto: clasifica vistas, elige las mejores
y escribe un 'brief' (partes, materiales, piezas móviles) que luego usa el director de animación."""
import os, io, re, json, base64, urllib.request
from PIL import Image

VISTAS = ["frontal", "trasera", "lateral_izquierda", "lateral_derecha", "superior", "inferior",
          "tres_cuartos", "detalle", "textura", "otro"]
CLAVES = {
    "frontal": ("frente", "front", "frontal", "delantera"),
    "trasera": ("atras", "back", "trasera", "rear", "espalda"),
    "lateral_izquierda": ("izq", "left", "izquierda"),
    "lateral_derecha": ("der", "right", "derecha"),
    "superior": ("top", "arriba", "superior", "cenital"),
    "detalle": ("detalle", "detail", "closeup", "zoom", "cerca"),
    "textura": ("textura", "texture", "material"),
}
PROMPT = """Te paso {n} imágenes (numeradas 1..{n} en orden) de UN MISMO objeto, personaje o vehículo para convertirlo en un modelo 3D de videojuego para Roblox. Pueden ser ángulos distintos, planos cercanos y lejanos, detalles o texturas.
Responde SOLO con un JSON válido (sin texto extra) con esta forma exacta:
{{"imagenes":[{{"indice":1,"vista":"frontal|trasera|lateral_izquierda|lateral_derecha|superior|inferior|tres_cuartos|detalle|textura|otro","calidad":1-5,"fondo_limpio":true,"nota":"breve"}}],
"mejor":{{"frontal":N,"trasera":N,"lateral_izquierda":N,"lateral_derecha":N}},
"descripcion":"qué es y cómo se ve, 2-4 frases",
"partes":[{{"nombre":"mandibula","descripcion":"...","movil":true,"movimiento":"cómo se movería"}}],
"materiales":["..."],"colores":["#RRGGBB"],"advertencias":["inconsistencias entre imágenes, vistas que faltan, etc."]}}
En "mejor" pon el índice de la mejor imagen para esa vista (o null si no hay). Las vistas de detalle/textura NO van en "mejor"."""


def _jpeg_b64(path, lado=768):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fondo = Image.new("RGB", im.size, (255, 255, 255))
        fondo.paste(im, mask=im.getchannel("A"))
        im = fondo
    else:
        im = im.convert("RGB")
    im.thumbnail((lado, lado))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _post(url, body, headers, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _json(texto):
    m = re.search(r"\{.*\}", texto, flags=re.S)
    if not m:
        raise ValueError("el modelo no devolvió JSON")
    return json.loads(m.group(0))


def por_nombre(paths):
    """Plan B sin IA: adivina la vista por el nombre del archivo."""
    imgs, mejor = [], {}
    for i, p in enumerate(paths, 1):
        n = os.path.basename(p).lower()
        vista = "otro"
        for v, ks in CLAVES.items():
            if any(k in n for k in ks):
                vista = v; break
        imgs.append({"indice": i, "vista": vista, "calidad": 3, "fondo_limpio": True, "nota": "por nombre de archivo"})
        if vista in ("frontal", "trasera", "lateral_izquierda", "lateral_derecha") and vista not in mejor:
            mejor[vista] = i
    if "frontal" not in mejor and paths:
        mejor["frontal"] = 1
    return {"imagenes": imgs, "mejor": mejor, "descripcion": "", "partes": [], "materiales": [], "colores": [],
            "advertencias": ["Sin análisis de IA: vistas deducidas por el nombre del archivo (frente, atras, izq, der...)."]}


def analizar(paths, cfg, log=print):
    backend = cfg.get("backend", "")
    key = cfg.get("api_key", "")
    try:
        if backend.startswith("Claude") and key:
            ims = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_b64(p)}} for p in paths]
            body = {"model": cfg.get("modelo", "claude-sonnet-5-5"), "max_tokens": 3500,
                    "messages": [{"role": "user", "content": ims + [{"type": "text", "text": PROMPT.format(n=len(paths))}]}]}
            r = _post("https://api.anthropic.com/v1/messages", body, {"x-api-key": key, "anthropic-version": "2023-06-01"})
            data = _json("".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text"))
        elif backend.startswith("Ollama"):
            usar = paths[:8]
            if len(paths) > 8:
                log(f"Ollama analiza como máximo 8 imágenes (hay {len(paths)}); para analizar todas usa Claude por API.")
            body = {"model": cfg.get("vision_modelo", "qwen2.5vl:7b"), "stream": False, "options": {"temperature": 0.2},
                    "messages": [{"role": "user", "content": PROMPT.format(n=len(usar)), "images": [_jpeg_b64(p, 640) for p in usar]}]}
            r = _post("http://localhost:11434/api/chat", body, {})
            data = _json(r["message"]["content"])
        else:
            raise RuntimeError("sin cerebro de visión configurado")
        data.setdefault("mejor", {})
        data.setdefault("partes", [])
        return data
    except Exception as e:
        log(f"No pude analizar con IA ({str(e)[:100]}); uso los nombres de archivo.")
        return por_nombre(paths)


def resumen(brief):
    t = []
    if brief.get("descripcion"):
        t.append(brief["descripcion"])
    if brief.get("partes"):
        t.append("Partes: " + "; ".join(f"{p.get('nombre')}{' (móvil: ' + str(p.get('movimiento')) + ')' if p.get('movil') else ''}" for p in brief["partes"]))
    if brief.get("materiales"):
        t.append("Materiales: " + ", ".join(map(str, brief["materiales"])))
    if brief.get("advertencias"):
        t.append("Avisos: " + " | ".join(map(str, brief["advertencias"])))
    return "\n".join(t)
