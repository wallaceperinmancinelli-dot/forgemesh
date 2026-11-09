"""Motores imagen→3D. 'cloud' usa Spaces gratuitos de Hugging Face (sin GPU propia);
'local' usa Hunyuan3D-2 en tu GPU NVIDIA si está instalado."""
import os, glob, shutil, tempfile

MESH_EXT = (".glb", ".gltf", ".obj", ".ply", ".fbx")
DEFAULT_SPACES = ["tencent/Hunyuan3D-2.1", "trellis-community/TRELLIS", "JeffreyXiang/TRELLIS", "microsoft/TRELLIS",
                  "victor/Hunyuan3D-2.1", "tencent/Hunyuan3D-2", "tencent/Hunyuan3D-2mini-Turbo"]
MULTI_SPACES = ["trellis-community/TRELLIS", "JeffreyXiang/TRELLIS", "microsoft/TRELLIS", "tencent/Hunyuan3D-2mv"]
_MALOS = {"CONFIG_ERROR", "BUILD_ERROR", "RUNTIME_ERROR", "PAUSED", "NO_APP_FILE", "STOPPED", "DELETING"}


def _estado(space):
    import json, urllib.request
    try:
        with urllib.request.urlopen(f"https://huggingface.co/api/spaces/{space}", timeout=10) as r:
            return (json.load(r).get("runtime") or {}).get("stage")
    except Exception:
        return None


def _descubrir(multi, log):
    """Busca en Hugging Face otros Spaces de imagen a 3D que esten funcionando."""
    import json, urllib.request, urllib.parse
    out = []
    for q in (["hunyuan3d mv", "trellis"] if multi else ["hunyuan3d", "trellis", "image to 3d"]):
        try:
            url = "https://huggingface.co/api/spaces?sort=likes&direction=-1&limit=12&search=" + urllib.parse.quote(q)
            with urllib.request.urlopen(url, timeout=10) as r:
                for d in json.load(r):
                    if d.get("sdk") == "gradio" and d.get("id") not in out and any(w in d.get("id", "").lower() for w in ("hunyuan", "trellis", "3d", "tripo", "triposr", "hi3dgen", "step1x")):
                        out.append(d["id"])
        except Exception:
            pass
    return out


def _spaces_validos(base, multi, log):
    res, vistos = [], set()
    for sp in list(base) + [None]:
        if sp is None:
            nuevos = [x for x in _descubrir(multi, log) if x not in vistos]
            if nuevos:
                log("Buscando otros Spaces de 3D disponibles...")
            lista = nuevos
        else:
            lista = [sp]
        for x in lista:
            vistos.add(x)
            st = _estado(x)
            if st in _MALOS:
                log(f"  {x} esta roto ({st}), lo salto.")
                continue
            res.append(x)
    return res


def _find_meshes(res, out=None):
    out = [] if out is None else out
    if isinstance(res, str):
        if res.lower().endswith(MESH_EXT) and os.path.exists(res):
            out.append(res)
    elif isinstance(res, dict):
        for v in res.values():
            _find_meshes(v, out)
    elif isinstance(res, (list, tuple)):
        for it in res:
            _find_meshes(it, out)
    return out


def _find_mesh(res):
    r = _find_meshes(res)
    return r[0] if r else None


def _textured(path):
    try:
        import trimesh
        m = trimesh.load(path, force="mesh", process=False)
        return getattr(m.visual, "kind", "") == "texture"
    except Exception:
        return False


def _is_image_param(p):
    t = (str(p.get("python_type", "")) + str(p.get("type", "")) + str(p.get("component", ""))).lower()
    return "image" in t or "filepath" in t or "gallery" in t


def _image_params(ep):
    return [p for p in ep.get("parameters", []) if _is_image_param(p)]


def _view_of_param(p):
    n = (str(p.get("parameter_name", "")) + " " + str(p.get("label", ""))).lower()
    for key, vista in (("front", "frontal"), ("back", "trasera"), ("rear", "trasera"),
                       ("left", "lateral_izquierda"), ("right", "lateral_derecha"), ("top", "superior")):
        if key in n:
            return vista
    return "frontal"


def _is_list_param(p):
    t = (str(p.get("python_type", "")) + str(p.get("type", "")) + str(p.get("component", ""))).lower()
    return "list" in t or "gallery" in t


def mapear_vistas(ep, vistas):
    """Devuelve (kwargs de imágenes, nº de vistas distintas usadas) para un endpoint, o (None, 0)."""
    from gradio_client import handle_file
    ips = _image_params(ep)
    if not ips:
        return None, 0
    kw, usadas = {}, set()
    for p in ips:
        if _is_list_param(p):
            kw[p["parameter_name"]] = [handle_file(v) for v in vistas.values()]
            usadas |= set(vistas)
            continue
        vista = _view_of_param(p)
        if vista in vistas:
            kw[p["parameter_name"]] = handle_file(vistas[vista])
            usadas.add(vista)
    if not kw:
        return None, 0
    return kw, len(usadas)


def list_endpoints(space, token=None):
    from gradio_client import Client
    tk = token or os.environ.get("HF_TOKEN") or None
    try:
        c = Client(space, token=tk, verbose=False)
    except TypeError:
        c = Client(space, hf_token=tk, verbose=False)
    info = c.view_api(return_format="dict")
    return c, info.get("named_endpoints", {})


def _defaults(ep, skip=()):
    return {p["parameter_name"]: (p.get("parameter_default") if p.get("parameter_has_default") else None)
            for p in ep["parameters"] if p["parameter_name"] not in skip}


def _trellis_flow(c, eps, vistas, multi, log):
    """TRELLIS: image_to_3d -> extract_glb (dos pasos con sesion). Soporta varias vistas."""
    from gradio_client import handle_file
    if "/start_session" in eps:
        try:
            c.predict(api_name="/start_session")
        except Exception:
            pass
    ep = eps["/image_to_3d"]
    paths = list(vistas.values())
    kw = _defaults(ep, skip=("image", "multiimages"))
    nombres = [p["parameter_name"] for p in ep["parameters"]]
    if multi and len(paths) >= 2 and "multiimages" in nombres:
        kw["image"] = None
        kw["multiimages"] = [{"image": handle_file(p), "caption": None} for p in paths[:8]]
        if "multiimage_algo" in nombres:
            kw["multiimage_algo"] = "stochastic"
        log(f"TRELLIS con {min(len(paths), 8)} vistas...")
    else:
        kw["image"] = handle_file(paths[0])
        if "multiimages" in nombres:
            kw["multiimages"] = []
        log("TRELLIS con 1 vista...")
    c.predict(api_name="/image_to_3d", **kw)
    ex = eps["/extract_glb"]
    kw2 = _defaults(ex)
    if "mesh_simplify" in kw2:
        kw2["mesh_simplify"] = 0.95
    if "texture_size" in kw2:
        kw2["texture_size"] = 1024
    log("TRELLIS: extrayendo modelo con textura...")
    res = c.predict(api_name="/extract_glb", **kw2)
    cands = _find_meshes(res)
    return cands[0] if cands else None


def generate_cloud(image_path, spaces=None, token=None, log=print, multi=False):
    """image_path: ruta (una vista) o dict {vista: ruta}. multi=True exige endpoints con 2+ vistas."""
    vistas = image_path if isinstance(image_path, dict) else {"frontal": image_path}
    last_err = None
    fallback = None
    errores = []
    for space in (_spaces_validos(spaces, multi, log) if spaces else _spaces_validos(MULTI_SPACES if multi else DEFAULT_SPACES, multi, log)):
        try:
            log(f"Conectando a {space} ...")
            c, eps = list_endpoints(space, token)
            if "/image_to_3d" in eps and "/extract_glb" in eps:
                m = _trellis_flow(c, eps, vistas, multi, log)
                if m:
                    out = os.path.join(tempfile.mkdtemp(), "raw" + os.path.splitext(m)[1])
                    shutil.copy(m, out)
                    return out
                continue

            def _prio(kv):
                n = kv[0].lower()
                if any(w in n for w in ("all", "textur", "full")):
                    return 0
                return 1 if any(w in n for w in ("generat", "image_to_3d", "3d", "shape")) else 2
            order = sorted(eps.items(), key=_prio)
            tried = 0
            for name, ep in order:
                imgkw, n_vistas = mapear_vistas(ep, vistas)
                if not imgkw or (multi and n_vistas < 2):
                    continue
                kwargs = dict(imgkw)
                for p in ep["parameters"]:
                    if p["parameter_name"] in kwargs:
                        continue
                    kwargs[p["parameter_name"]] = p.get("parameter_default") if p.get("parameter_has_default") else None
                log(f"Generando con {space}{name} usando {n_vistas} vista(s) (puede tardar 1-5 min, hay cola gratuita)...")
                try:
                    res = c.predict(api_name=name, **kwargs)
                except Exception as e:
                    last_err = e
                    log(f"  endpoint {name} falló: {str(e)[:120]}")
                    continue
                cands = _find_meshes(res)
                tried += 1
                best = next((x for x in cands if _textured(x)), None)
                if best or (cands and tried >= 2):
                    m = best or cands[0]
                    if not best:
                        log("Aviso: este resultado vino sin textura de color.")
                    out = os.path.join(tempfile.mkdtemp(), "raw" + os.path.splitext(m)[1])
                    shutil.copy(m, out)
                    return out
                if cands:
                    log("Resultado sin textura, probando otro endpoint para obtener color...")
                    fallback = cands[0]
        except Exception as e:
            last_err = e
            log(f"  {space} no disponible: {str(e)[:140]}")
            errores.append(f"{space}: {str(e)[:90]}")
    if fallback:
        out = os.path.join(tempfile.mkdtemp(), "raw" + os.path.splitext(fallback)[1])
        shutil.copy(fallback, out)
        return out
    if any("quota" in e.lower() for e in errores):
        raise RuntimeError(
            "Los servidores gratis funcionan, pero se te acabó la cuota diaria de GPU de Hugging Face "
            "(sin cuenta es casi cero). Solución: creá una cuenta gratis en huggingface.co, andá a Settings → "
            "Access Tokens → New token (tipo Read), copiá el token y pegalo en ForgeMesh → Ajustes → "
            "'Token de Hugging Face' → Guardar. Con cuenta gratis tenés unos 3-4 minutos de GPU por día "
            "(alcanza para varios modelos); con Hugging Face PRO (9 USD/mes) tenés 25 minutos. "
            "Detalle: " + " | ".join(errores)[:300])
    raise RuntimeError(f"[v7] Ningún Space respondió. Probados: {chr(10).join(errores) or 'ninguno (todos marcados rotos o sin internet)'}. Último error: {last_err}. "
                       "Prueba de nuevo en unos minutos o añade tu token de Hugging Face (más cuota).")


_local_cache = {}


def generate_local(image_path, texture=True, log=print):
    """Hunyuan3D-2 en GPU NVIDIA propia (requiere instalar_local.bat)."""
    from PIL import Image
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    img = Image.open(image_path).convert("RGBA")
    if "shape" not in _local_cache:
        log("Cargando modelo de forma (primera vez descarga ~5 GB)...")
        _local_cache["shape"] = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained("tencent/Hunyuan3D-2")
    mesh = _local_cache["shape"](image=img, num_inference_steps=40, octree_resolution=256)[0]
    if texture:
        from hy3dgen.texgen import Hunyuan3DPaintPipeline
        if "tex" not in _local_cache:
            log("Cargando modelo de textura...")
            _local_cache["tex"] = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2")
        mesh = _local_cache["tex"](mesh, image=img)
    out = os.path.join(tempfile.mkdtemp(), "raw.glb")
    mesh.export(out)
    return out
