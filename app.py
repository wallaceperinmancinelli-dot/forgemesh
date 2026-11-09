import os, re, json, tempfile, traceback, urllib.request
import gradio as gr
from PIL import Image
import optimize as opt
import engines, materials, parts, templates, analysis, ajustes

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "salida")
os.makedirs(OUT_DIR, exist_ok=True)


def prep_image(path, quitar_fondo):
    img = Image.open(path).convert("RGBA")
    if quitar_fondo:
        try:
            from rembg import remove
            img = remove(img)
        except Exception as e:
            print("rembg no disponible:", e)
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    s = int(max(img.size) * 1.15)
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas.paste(img, ((s - img.width) // 2, (s - img.height) // 2), img)
    p = os.path.join(tempfile.mkdtemp(), "in.png")
    canvas.save(p)
    return p


def _unique(nombre):
    out = os.path.join(OUT_DIR, nombre + ".glb")
    i = 1
    while os.path.exists(out):
        out = os.path.join(OUT_DIR, f"{nombre}_{i}.glb"); i += 1
    return out


def _finish(raw, preset, tris, altura, nombre, metal, fuerza, saturar, mapas, log):
    nombre = (nombre or "modelo").strip().replace(" ", "_")
    out = _unique(nombre)
    opt.optimize(raw, out, preset, int(tris) if tris else None, float(altura) if altura else None, log=log)
    base = os.path.splitext(out)[0]
    mdir = base + "_mapas" if mapas else None
    mask = None
    if metal != materials.MODOS[2] or saturar or mapas:
        try:
            mask = materials.enhance(out, metal, fuerza, saturar, mdir, log=log)
        except Exception as e:
            log(f"Material PBR omitido: {e}")
    files = [out]
    try:
        m = opt.load_mesh(out); obj = base + ".obj"; m.export(obj); files.append(obj)
    except Exception:
        pass
    return out, files, mask


def _rutas(files):
    if not files:
        return []
    if not isinstance(files, (list, tuple)):
        files = [files]
    return [f if isinstance(f, str) else getattr(f, "name", str(f)) for f in files]


def run(imgs, motor, preset, tris, altura, quitar_fondo, nombre, metal, fuerza, saturar, mapas,
        progress=gr.Progress()):
    logs = []
    log = lambda m: (logs.append(m), print(m))
    try:
        paths = _rutas(imgs)
        if not paths:
            raise gr.Error("Sube al menos una imagen.")
        cfg = ajustes.cargar()
        token = cfg.get("hf_token") or None
        brief_txt = ""
        vistas = {}
        if len(paths) > 1:
            progress(0.03, desc=f"Analizando {len(paths)} imágenes")
            brief = analysis.analizar(paths, cfg, log=log)
            brief_txt = analysis.resumen(brief)
            nombre_s = (nombre or "modelo").strip().replace(" ", "_")
            try:
                with open(os.path.join(OUT_DIR, nombre_s + "_brief.json"), "w", encoding="utf-8") as f:
                    json.dump(brief, f, indent=1, ensure_ascii=False)
            except Exception:
                pass
            for vista, idx in (brief.get("mejor") or {}).items():
                if isinstance(idx, int) and 1 <= idx <= len(paths):
                    vistas[vista] = paths[idx - 1]
            log("Vistas elegidas: " + ", ".join(f"{v} → imagen {paths.index(p) + 1}" for v, p in vistas.items()))
        if not vistas:
            vistas = {"frontal": paths[0]}
        if "frontal" not in vistas:
            vistas["frontal"] = next(iter(vistas.values()))
        progress(0.1, desc="Preparando imágenes")
        prep = {v: prep_image(p, quitar_fondo) for v, p in vistas.items()}
        progress(0.2, desc="Generando 3D")
        if motor.startswith("Local"):
            raw = engines.generate_local(prep["frontal"], log=log)
        else:
            raw = None
            if len(prep) > 1:
                try:
                    raw = engines.generate_cloud(prep, token=token, log=log, multi=True)
                except Exception as e:
                    log(f"Modo multivista no disponible ({str(e)[:90]}); uso la mejor vista frontal.")
            if raw is None:
                raw = engines.generate_cloud(prep["frontal"], token=token, log=log)
        progress(0.8, desc="Optimizando y aplicando materiales")
        out, files, mask = _finish(raw, preset, tris, altura, nombre, metal, fuerza, saturar, mapas, log)
        return out, files, "\n".join(logs), mask, out, brief_txt, brief_txt
    except gr.Error:
        raise
    except Exception as e:
        traceback.print_exc()
        return None, None, "ERROR: " + str(e), None, None, "", ""


def solo_optimizar(modelo, preset, tris, altura, metal, fuerza, saturar, mapas):
    if modelo is None:
        raise gr.Error("Sube un modelo (.glb/.obj/.fbx/.ply).")
    logs = []
    try:
        nombre = "opt_" + os.path.splitext(os.path.basename(modelo))[0]
        out, files, mask = _finish(modelo, preset, tris, altura, nombre, metal, fuerza, saturar, mapas, logs.append)
        return out, files, "\n".join(logs), mask, out
    except Exception as e:
        traceback.print_exc()
        return None, None, "ERROR: " + str(e), None, None


def separar(modelo, nombre, cortes):
    if not modelo:
        raise gr.Error("Sube o genera un modelo .glb primero.")
    logs = []
    try:
        nombre = (nombre or "modelo").strip().replace(" ", "_")
        outdir = os.path.join(OUT_DIR, nombre + "_partes")
        info = parts.separar(modelo, outdir, nombre, cortes=cortes, log=logs.append)
        files = [os.path.join(outdir, f) for f in sorted(os.listdir(outdir)) if f.endswith((".obj", ".png"))]
        return "\n".join(logs), parts.plantilla_animacion(info), outdir, files
    except Exception as e:
        traceback.print_exc()
        return "ERROR: " + str(e), "", "", None


def generar_script(outdir, anim, clips, color_id, metal_id, rough_id):
    import json
    try:
        with open(os.path.join(outdir, "partes.json"), encoding="utf-8") as f:
            info = json.load(f)
    except Exception:
        raise gr.Error("Primero separa el modelo en piezas.")
    code, errores = parts.generar_luau(info, anim, clips, color_id.strip(), metal_id.strip(), rough_id.strip())
    path = os.path.join(outdir, f"Anim_{info['modelo']}.lua")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    aviso = ("Avisos:\n" + "\n".join(errores) + "\n\n") if errores else ""
    return aviso + "Script guardado en: " + path, code, path


KB_PATH = os.path.join(BASE, "conocimiento_roblox.md")


def _kb():
    try:
        with open(KB_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "Eres un experto en animación y modelos 3D para Roblox. Responde en español."


def _info(outdir):
    try:
        with open(os.path.join(outdir, "partes.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _contexto(outdir, anim, clips, hay_modelo, brief=""):
    txt = "\n\n# CONTEXTO ACTUAL\n"
    if brief:
        txt += "Resumen de las imágenes de referencia del usuario (interpretado por visión):\n" + brief + "\n\n"
    info = _info(outdir or "")
    if info:
        txt += f"Modelo: {info['modelo']}. Piezas (nombre · tamaño studs [x,y,z] · triángulos · centro relativo a la pieza principal):\n"
        for p in info["piezas"]:
            tam = [round(2 * x, 1) for x in p["mitad"]]
            off = [round(x, 1) for x in p["offset"]]
            txt += f"- {p['nombre']} · {tam} · {p['tris']} tris · {off}\n"
        if info.get("alias"):
            txt += "Alias: " + ", ".join(f"{k}={v}" for k, v in info["alias"].items()) + "\n"
    elif hay_modelo:
        txt += "Hay un modelo generado pero aún NO separado en piezas (usa la acción `separar` o escribe las animaciones y se separará solo).\n"
    else:
        txt += "Todavía no hay ningún modelo generado.\n"
    if anim and anim.strip():
        txt += "\nCapas actuales:\n" + anim.strip() + "\n"
    if clips and clips.strip():
        txt += "\nClips actuales:\n" + clips.strip() + "\n"
    return txt


def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def _txt(c):
    if isinstance(c, list):
        return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in c)
    return str(c or "")


def _llm(backend, modelo, key, msgs, ctx):
    if backend.startswith("Ollama"):
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
                inst = [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]
        except Exception:
            raise RuntimeError("Ollama no está abierto o no está instalado. Instálalo gratis desde ollama.com "
                               "(o en Ajustes elige 'Claude API' y pon tu clave).")
        if modelo not in inst and f"{modelo}:latest" not in inst:
            if inst:
                modelo = inst[0]
            else:
                # no hay ningun modelo: descargar uno automaticamente (una sola vez, ~4.7 GB)
                urllib.request.urlopen(urllib.request.Request("http://localhost:11434/api/pull",
                    data=json.dumps({"model": modelo, "stream": False}).encode(),
                    headers={"content-type": "application/json"}), timeout=3600).read()
        body = {"model": modelo, "stream": False, "options": {"num_ctx": 10240, "temperature": 0.3},
                "messages": [{"role": "system", "content": _kb() + ctx}] + msgs}
        return _post("http://localhost:11434/api/chat", body, {})["message"]["content"]
    if not key:
        raise RuntimeError("Falta la API key de Anthropic.")
    body = {"model": modelo, "max_tokens": 3000, "messages": msgs,
            "system": [{"type": "text", "text": _kb(), "cache_control": {"type": "ephemeral"}},
                       {"type": "text", "text": ctx}]}
    r = _post("https://api.anthropic.com/v1/messages", body, {"x-api-key": key, "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")


def _bloques(texto):
    out = {}
    for nombre, cuerpo in re.findall(r"```(anim|clips|cortes|alias|accion)\s*\n(.*?)```", texto or "", flags=re.S):
        out.setdefault(nombre, []).append(cuerpo.strip())
    return {k: "\n".join(v) for k, v in out.items()}


def _merge_anim(actual, nuevo):
    def por_pieza(txt):
        d, orden = {}, []
        for ln in (txt or "").splitlines():
            if ":" in ln:
                k = ln.split(":", 1)[0].strip()
                if k not in d:
                    d[k] = []; orden.append(k)
                d[k].append(ln.strip())
        return d, orden
    d, orden = por_pieza(actual)
    n, orden_n = por_pieza(nuevo)
    for k in orden_n:
        if k not in d:
            orden.append(k)
        d[k] = n[k]
    return "\n".join(l for k in orden for l in d[k])


def _split_clips(txt):
    d, cur = {}, None
    for ln in (txt or "").splitlines():
        m = re.match(r"^clip\s+(\w+)", ln.strip(), flags=re.I)
        if m:
            cur = m.group(1).lower(); d[cur] = [ln.strip()]
        elif cur and ln.strip():
            d[cur].append(ln.strip())
    return d


def _merge_clips(actual, nuevo):
    d = _split_clips(actual)
    d.update(_split_clips(nuevo))
    return "\n".join("\n".join(v) for v in d.values())


def agente(msg, hist, mod, ultimo, nombre, carpeta, anim, clips, cortes, c_id, m_id, r_id, brief):
    """Chat con autopiloto: entiende la instrucción y ejecuta todo (separar, animar, scripts)."""
    hist = list(hist or [])
    res = {"anim": anim, "clips": clips, "cortes": cortes, "carpeta": carpeta, "codigo": gr.update(), "lua": gr.update()}
    if not (msg or "").strip():
        return ["", hist, anim, clips, cortes, carpeta, res["codigo"], res["lua"]]
    hist.append({"role": "user", "content": msg})
    msgs = [{"role": h["role"], "content": _txt(h["content"])} for h in hist[-8:]]
    fuente = mod or ultimo
    cfg = ajustes.cargar()
    try:
        ans = _llm(cfg["backend"], cfg["modelo"], cfg["api_key"], msgs, _contexto(carpeta, anim, clips, bool(fuente), brief))
    except Exception as e:
        hist.append({"role": "assistant", "content": "No pude hablar con el modelo: " + str(e) +
                     "\n\nSi usas Ollama: ábrelo y revisa que el modelo esté instalado (botón 'Ver modelos de Ollama')."})
        return ["", hist, anim, clips, cortes, carpeta, res["codigo"], res["lua"]]

    log = []
    try:
        bl = _bloques(ans)
        acciones = [l.strip().lower() for l in bl.get("accion", "").splitlines() if l.strip()]
        quiere = ("anim" in bl or "clips" in bl or "cortes" in bl or any(a.startswith(("separar", "plantilla", "script", "plataforma")) for a in acciones))
        if "cortes" in bl:
            res["cortes"] = bl["cortes"]
        info = _info(res["carpeta"] or "")
        if quiere and (info is None or "cortes" in bl or "separar" in acciones):
            if not fuente:
                raise RuntimeError("Primero genera un modelo en la pestaña 'Imagen a 3D' (o sube un .glb en 'Piezas y animación').")
            nom = (nombre or "modelo").strip().replace(" ", "_")
            outdir = os.path.join(OUT_DIR, nom + "_partes")
            info = parts.separar(fuente, outdir, nom, cortes=res["cortes"], log=lambda m: None)
            res["carpeta"] = outdir
            log.append(f"✔ Modelo separado en {len(info['piezas'])} piezas")
        if info is None:
            hist.append({"role": "assistant", "content": ans})
            return ["", hist, anim, clips, res["cortes"], res["carpeta"], res["codigo"], res["lua"]]
        cambio = False
        if "alias" in bl:
            info.setdefault("alias", {})
            for ln in bl["alias"].splitlines():
                if "=" in ln:
                    k, v = ln.split("=", 1)
                    k = k.strip()
                    if k in {p["nombre"] for p in info["piezas"]}:
                        info["alias"][parts._norm(v)] = k
            with open(os.path.join(res["carpeta"], "partes.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, indent=1)
            log.append("✔ Nombres de piezas guardados")
        for a in acciones:
            if a.startswith("plantilla"):
                tk = a.split()
                nombre_pl = tk[1] if len(tk) > 1 else ""
                kv = dict(t.split("=", 1) for t in tk[2:] if "=" in t)
                roles = {}
                for k, v in kv.items():
                    if k == "frente":
                        continue
                    roles[k] = [r for r in (parts._real(x, info) for x in v.split(",")) if r]
                la, lc = templates.aplicar(nombre_pl, info, roles, kv.get("frente", "+z"))
                res["anim"] = _merge_anim(res["anim"], "\n".join(la))
                res["clips"] = _merge_clips(res["clips"], lc)
                log.append(f"✔ Plantilla '{nombre_pl}' aplicada ({len(_split_clips(lc))} clips)")
                cambio = True
        if "anim" in bl:
            res["anim"] = _merge_anim(res["anim"], bl["anim"]); cambio = True
        if "clips" in bl:
            res["clips"] = _merge_clips(res["clips"], bl["clips"]); cambio = True
        if cambio or "script" in acciones:
            code, errores = parts.generar_luau(info, res["anim"], res["clips"], c_id.strip(), m_id.strip(), r_id.strip())
            path = os.path.join(res["carpeta"], f"Anim_{info['modelo']}.lua")
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            res["codigo"], res["lua"] = code, path
            log.append(f"✔ Script generado: {path}")
            for e in errores:
                log.append("⚠ " + e)
        if "plataforma" in acciones:
            p = os.path.join(res["carpeta"], "Plataforma.lua")
            with open(p, "w", encoding="utf-8") as f:
                f.write(parts.luau_plataforma())
            log.append(f"✔ Script de plataforma móvil: {p}")
    except Exception as e:
        traceback.print_exc()
        log.append("✘ " + str(e))
    final = ans + ("\n\n---\n" + "\n".join(log) if log else "")
    hist.append({"role": "assistant", "content": final})
    return ["", hist, res["anim"], res["clips"], res["cortes"], res["carpeta"], res["codigo"], res["lua"]]


def guardar_ajustes(backend, modelo, vision, key, hf, url, auto):
    ajustes.guardar(backend=backend, modelo=modelo, vision_modelo=vision, api_key=(key or "").strip(),
                    hf_token=(hf or "").strip(), update_url=(url or "").strip(), auto_update=bool(auto))
    return "✔ Guardado"


def modelos_ollama():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            names = [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]
        return gr.update(choices=names, value=(names[0] if names else None))
    except Exception:
        raise gr.Error("Ollama no responde. Ábrelo (o instálalo desde ollama.com) y vuelve a intentar.")


def script_plataforma():
    return parts.luau_plataforma()


MODOS = materials.MODOS

with gr.Blocks(title="ForgeMesh – Imagen a 3D para juegos") as demo:
    gr.Markdown("# ForgeMesh\nImagen → modelo 3D → materiales → piezas → animación (Roblox, Unity, Unreal, Godot).")
    ultimo = gr.State(None)
    brief = gr.State("")
    with gr.Tab("Imagen a 3D"):
        with gr.Row():
            with gr.Column():
                img = gr.File(file_count="multiple", file_types=["image"], label="Imágenes de referencia (1 o muchas: ángulos, cerca y lejos, detalles)")
                motor = gr.Radio(["Nube gratis (sin GPU)", "Local (GPU NVIDIA)"], value="Nube gratis (sin GPU)", label="Motor")
                preset = gr.Dropdown(list(opt.PRESETS), value="Roblox (20k tris, tex 1024)", label="Preset de juego")
                with gr.Row():
                    tris = gr.Number(label="Triángulos (opcional, pisa el preset)", value=None)
                    altura = gr.Number(label="Altura final (studs / unidades)", value=None)
                with gr.Accordion("Color y metal (dorado, acero, PBR)", open=True):
                    metal = gr.Dropdown(MODOS, value=MODOS[0], label="Detectar metal en la textura")
                    fuerza = gr.Slider(0, 1, value=1.0, step=0.05, label="Intensidad del metal")
                    saturar = gr.Checkbox(False, label="Realzar colores (más saturación y contraste)")
                    mapas = gr.Checkbox(True, label="Guardar mapas para Roblox (color / metalness / roughness)")
                quitar = gr.Checkbox(True, label="Quitar fondo automáticamente")
                nombre = gr.Textbox("modelo", label="Nombre del archivo")
                btn = gr.Button("Generar modelo 3D", variant="primary")
            with gr.Column():
                view = gr.Model3D(label="Vista previa", height=480)
                files = gr.File(label="Archivos (también en la carpeta 'salida')", file_count="multiple")
                maskimg = gr.Image(label="Zonas detectadas como metal (blanco = metal)", type="pil")
                briefbox = gr.Textbox(label="Lo que entendí de tus imágenes", lines=5)
                logbox = gr.Textbox(label="Registro", lines=6)
        btn.click(run, [img, motor, preset, tris, altura, quitar, nombre, metal, fuerza, saturar, mapas],
                  [view, files, logbox, maskimg, ultimo, briefbox, brief])

    with gr.Tab("Optimizar un modelo que ya tengo"):
        m = gr.File(label="Modelo (.glb .obj .fbx .ply)")
        p2 = gr.Dropdown(list(opt.PRESETS), value="Roblox (20k tris, tex 1024)", label="Preset")
        t2 = gr.Number(label="Triángulos (opcional)"); a2 = gr.Number(label="Altura final (opcional)")
        me2 = gr.Dropdown(MODOS, value=MODOS[2], label="Detectar metal")
        fu2 = gr.Slider(0, 1, value=1.0, step=0.05, label="Intensidad del metal")
        sa2 = gr.Checkbox(False, label="Realzar colores")
        ma2 = gr.Checkbox(False, label="Guardar mapas para Roblox")
        b2 = gr.Button("Optimizar", variant="primary")
        v2 = gr.Model3D(); f2 = gr.File(file_count="multiple"); k2 = gr.Image(type="pil", label="Máscara de metal"); l2 = gr.Textbox(lines=4)
        b2.click(solo_optimizar, [m, p2, t2, a2, me2, fu2, sa2, ma2], [v2, f2, l2, k2, ultimo])

    with gr.Tab("Piezas y animación"):
        gr.Markdown("1) Separa el modelo en piezas. 2) Escribe qué hace cada pieza. 3) Genera el script de Roblox "
                    "(todo se calcula aquí, sin gastar tokens de Claude).")
        mod = gr.File(label="Modelo .glb (si acabas de generar uno, usa el botón de abajo)")
        usar = gr.Button("Usar el último modelo generado")
        nom3 = gr.Textbox("modelo", label="Nombre del modelo")
        cortes = gr.Textbox(label="Cortes opcionales para piezas pegadas (ej: y=3.2   o   parte_01:y=3.2, parte_01:z=1)", lines=2)
        bsep = gr.Button("Separar en piezas", variant="primary")
        log3 = gr.Textbox(label="Registro", lines=8)
        carpeta = gr.Textbox(label="Carpeta de piezas", interactive=False)
        archivos3 = gr.File(label="Piezas (.obj) y texturas", file_count="multiple")
        gr.Markdown(parts.AYUDA)
        anim = gr.Textbox(label="Capas base (idle, ruedas, luces...)", lines=8)
        clips = gr.Textbox(label="Clips (rugido, mordisco, arranque...)", lines=10)
        with gr.Accordion("IDs de textura de Roblox (opcional, ahorra RAM compartiendo texturas)", open=False):
            c_id = gr.Textbox(label="ColorMap (rbxassetid://...)")
            m_id = gr.Textbox(label="MetalnessMap (rbxassetid://...)")
            r_id = gr.Textbox(label="RoughnessMap (rbxassetid://...)")
        bgen = gr.Button("Generar script Luau", variant="primary")
        log4 = gr.Textbox(label="Resultado", lines=3)
        codigo = gr.Textbox(label="Script Luau (copia y pega en un ModuleScript)", lines=18)
        archivo_lua = gr.File(label="Archivo .lua")
        bplat = gr.Button("Script de plataforma móvil (para que los jugadores viajen de pie en el tren)")
        plat = gr.Textbox(label="LocalScript de plataforma móvil", lines=12)
        bplat.click(script_plataforma, None, [plat])
        usar.click(lambda u: u, [ultimo], [mod])
        bsep.click(separar, [mod, nom3, cortes], [log3, anim, carpeta, archivos3])
        bgen.click(generar_script, [carpeta, anim, clips, c_id, m_id, r_id], [log4, codigo, archivo_lua])

    with gr.Tab("Chat / asistente"):
        gr.Markdown("Dale instrucciones en lenguaje normal (\"que la mandíbula se abra con rebote cada 3 s\"). "
                    "Ejecuta todo solo: separa el modelo, anima y regenera el script. El cerebro se elige en **Ajustes**.")
        chat = gr.Chatbot(height=440, label="Chat")
        entrada = gr.Textbox(label="Instrucción", placeholder="Ej: parte_03 es la mandíbula; haz un monstruo aterrador con rugido y mordisco")
        with gr.Row():
            benv = gr.Button("Enviar", variant="primary")
            blim = gr.Button("Limpiar chat")
        ent = [entrada, chat, mod, ultimo, nom3, carpeta, anim, clips, cortes, c_id, m_id, r_id, brief]
        sal = [entrada, chat, anim, clips, cortes, carpeta, codigo, archivo_lua]
        entrada.submit(agente, ent, sal)
        benv.click(agente, ent, sal)
        blim.click(lambda: [], None, [chat])

    with gr.Tab("Ajustes"):
        _c = ajustes.cargar()
        gr.Markdown("Se guardan una sola vez en `config.json` en tu PC. **Cerebro** = el que dirige las animaciones (chat) y analiza tus imágenes.")
        s_backend = gr.Radio(["Ollama (local, gratis)", "Claude (API key, de pago)"], value=_c["backend"], label="Cerebro")
        s_modelo = gr.Dropdown(["qwen2.5:7b", "llama3.1:8b", "claude-haiku-5-5", "claude-sonnet-5-5"], value=_c["modelo"],
                               allow_custom_value=True, label="Modelo del chat")
        s_vision = gr.Dropdown(["qwen2.5vl:7b", "llama3.2-vision", "llava"], value=_c["vision_modelo"],
                               allow_custom_value=True, label="Modelo de visión de Ollama (análisis de imágenes)")
        s_vermod = gr.Button("Ver modelos instalados en Ollama")
        s_key = gr.Textbox(value=_c["api_key"], label="API key de Anthropic (para Claude: mejor calidad, analiza hasta 20+ imágenes)", type="password")
        s_hf = gr.Textbox(value=_c["hf_token"], label="Token de Hugging Face (opcional, más cuota gratis)", type="password")
        s_url = gr.Textbox(value=_c["update_url"], label="URL de actualizaciones automáticas (te la doy yo; se pega una sola vez)")
        s_auto = gr.Checkbox(_c["auto_update"], label="Actualizar ForgeMesh automáticamente al abrirlo")
        s_btn = gr.Button("Guardar ajustes", variant="primary")
        s_msg = gr.Textbox(label="Estado", lines=1)
        s_vermod.click(modelos_ollama, None, [s_modelo])
        s_btn.click(guardar_ajustes, [s_backend, s_modelo, s_vision, s_key, s_hf, s_url, s_auto], [s_msg])

if __name__ == "__main__":
    import os, sys, socket, subprocess, shutil

    def _ventana(url):
        """Abre ForgeMesh como ventana de app (sin barra de navegador)."""
        for exe in (shutil.which("msedge"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
            if exe and os.path.exists(exe):
                subprocess.Popen([exe, f"--app={url}", "--window-size=1280,900"])
                return True
        import webbrowser
        webbrowser.open(url)
        return False

    def _acceso_directo():
        """Crea un icono ForgeMesh en el escritorio (una sola vez)."""
        if sys.platform != "win32":
            return
        base = os.path.dirname(os.path.abspath(__file__))
        marca = os.path.join(base, "venv", "acceso.txt")
        if os.path.exists(marca):
            return
        ps = ("$d=[Environment]::GetFolderPath('Desktop');$s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\\ForgeMesh.lnk');"
              f"$s.TargetPath='{base}\\INICIAR.bat';$s.WorkingDirectory='{base}';$s.WindowStyle=7;"
              "$s.IconLocation='shell32.dll,13';$s.Save()")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=20)
            open(marca, "w").write("ok")
        except Exception:
            pass

    _url = "http://127.0.0.1:7860"
    _s = socket.socket()
    _ya = _s.connect_ex(("127.0.0.1", 7860)) == 0
    _s.close()
    if _ya:  # ya esta corriendo: solo abrir la ventana
        _ventana(_url)
        sys.exit(0)
    _acceso_directo()
    demo.queue().launch(server_name="127.0.0.1", server_port=7860, inbrowser=False, prevent_thread_lock=True)
    _ventana(_url)
    demo.block_thread()
