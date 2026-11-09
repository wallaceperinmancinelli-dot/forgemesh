"""Motores imagen→3D. 'cloud' usa Spaces gratuitos de Hugging Face (sin GPU propia);
'local' usa Hunyuan3D-2 en tu GPU NVIDIA si está instalado."""
import os, glob, shutil, tempfile

MESH_EXT = (".glb", ".gltf", ".obj", ".ply", ".fbx")
DEFAULT_SPACES = ["tencent/Hunyuan3D-2.1", "tencent/Hunyuan3D-2", "microsoft/TRELLIS"]
MULTI_SPACES = ["tencent/Hunyuan3D-2mv", "microsoft/TRELLIS"]


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


def generate_cloud(image_path, spaces=None, token=None, log=print, multi=False):
    """image_path: ruta (una vista) o dict {vista: ruta}. multi=True exige endpoints con 2+ vistas."""
    vistas = image_path if isinstance(image_path, dict) else {"frontal": image_path}
    last_err = None
    fallback = None
    for space in (spaces or (MULTI_SPACES if multi else DEFAULT_SPACES)):
        try:
            log(f"Conectando a {space} ...")
            c, eps = list_endpoints(space, token)

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
    if fallback:
        out = os.path.join(tempfile.mkdtemp(), "raw" + os.path.splitext(fallback)[1])
        shutil.copy(fallback, out)
        return out
    raise RuntimeError(f"Ningún Space respondió. Último error: {last_err}. "
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
