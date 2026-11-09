"""Optimización de mallas para videojuegos (CPU, sin GPU)."""
import os, tempfile
import numpy as np
import trimesh

PRESETS = {
    # nombre: (triángulos objetivo, tamaño textura)
    "Roblox (20k tris, tex 1024)": (20000, 1024),
    "Móvil / low-poly (5k, tex 512)": (5000, 512),
    "Personaje / prop medio (30k, tex 2048)": (30000, 2048),
    "Alta calidad (100k, tex 4096)": (100000, 4096),
    "Sin reducir": (0, 0),
}


def load_mesh(path):
    obj = trimesh.load(path, force="mesh", process=False)
    if isinstance(obj, trimesh.Scene):
        obj = trimesh.util.concatenate(list(obj.geometry.values()))
    return obj


def _resize_texture(mesh, size):
    vis = mesh.visual
    mat = getattr(vis, "material", None)
    if mat is None or size <= 0:
        return
    for attr in ("baseColorTexture", "image"):
        img = getattr(mat, attr, None)
        if img is not None and max(img.size) > size:
            img = img.convert("RGBA") if img.mode not in ("RGB", "RGBA") else img
            ratio = size / max(img.size)
            new = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
            try:
                setattr(mat, attr, new)
            except Exception:
                pass


def _decimate_meshlab(mesh, target):
    import pymeshlab
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.obj"), os.path.join(d, "out.obj")
        mesh.export(src)
        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(src)
        has_uv = ms.current_mesh().has_wedge_tex_coord() or ms.current_mesh().has_vertex_tex_coord()
        if has_uv:
            ms.meshing_decimation_quadric_edge_collapse_with_texture(
                targetfacenum=target, preservenormal=True, qualitythr=0.5)
        else:
            ms.meshing_decimation_quadric_edge_collapse(
                targetfacenum=target, preservenormal=True, preserveboundary=True)
        ms.save_current_mesh(dst)
        return load_mesh(dst)


def _decimate_trimesh(mesh, target):
    return mesh.simplify_quadric_decimation(face_count=target)


def optimize(path_in, path_out, preset="Roblox (20k tris, tex 1024)", target_tris=None,
             height=None, pivot_bottom=True, log=print):
    tris, tex = PRESETS.get(preset, (20000, 1024))
    if target_tris:
        tris = int(target_tris)
    mesh = load_mesh(path_in)
    n0 = len(mesh.faces)
    log(f"Malla original: {n0:,} triángulos")

    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    mesh.merge_vertices()

    # quita islas flotantes diminutas (<0.5 % de las caras de la pieza mayor)
    parts = mesh.split(only_watertight=False)
    if len(parts) > 1:
        big = max(len(p.faces) for p in parts)
        keep = [p for p in parts if len(p.faces) >= big * 0.005]
        if len(keep) != len(parts):
            log(f"Eliminadas {len(parts) - len(keep)} islas flotantes")
            mesh = trimesh.util.concatenate(keep)

    if tris and len(mesh.faces) > tris:
        try:
            mesh = _decimate_meshlab(mesh, tris)
            log("Reducción con MeshLab (conserva UV/textura)")
        except Exception as e:
            log(f"MeshLab no disponible ({e.__class__.__name__}); uso reducción básica")
            mesh = _decimate_trimesh(mesh, tris)
    if tex:
        _resize_texture(mesh, tex)

    # orientación/escala/pivote: centrado en X/Z, base en Y=0
    b = mesh.bounds
    center = (b[0] + b[1]) / 2
    shift = np.array([-center[0], -b[0][1] if pivot_bottom else -center[1], -center[2]])
    mesh.apply_translation(shift)
    if height:
        cur = mesh.bounds[1][1] - mesh.bounds[0][1]
        if cur > 0:
            mesh.apply_scale(height / cur)

    mesh.export(path_out)
    log(f"Resultado: {len(mesh.faces):,} triángulos → {os.path.basename(path_out)}")
    return path_out, len(mesh.faces)
