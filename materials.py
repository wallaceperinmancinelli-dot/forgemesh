"""Materiales PBR: detecta dorado/metal en la textura y crea mapas de metalicidad y rugosidad."""
import os
import numpy as np
import trimesh
from PIL import Image, ImageFilter, ImageEnhance

MODOS = ["Dorado y bronce", "Dorado + plata/acero", "Ninguno (solo color)"]


def _texture(mesh):
    mat = getattr(mesh.visual, "material", None)
    if mat is None:
        return None
    img = getattr(mat, "baseColorTexture", None)
    if img is None:
        img = getattr(mat, "image", None)
    return img


def make_maps(img, modo, fuerza):
    rgb = img.convert("RGB")
    hsv = np.asarray(rgb.convert("HSV")).astype(np.float32) / 255.0
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # dorado/bronce: tono 25°–60°, saturación media, no demasiado oscuro; excluye naranja brillante (luces/fuego)
    gold = (h >= 0.07) & (h <= 0.17) & (s >= 0.30) & (v >= 0.30) & ~((s > 0.85) & (v > 0.88))
    mask = gold.astype(np.float32)
    if modo.startswith("Dorado +"):
        silver = (s < 0.14) & (v > 0.45) & (v < 0.92)
        mask = np.maximum(mask, silver.astype(np.float32))
    if modo.startswith("Ninguno"):
        mask = np.zeros_like(mask)
    m = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    mask = np.asarray(m).astype(np.float32) / 255.0
    mask = np.clip((mask - 0.25) / 0.5, 0, 1) * float(fuerza)
    rough = np.clip(0.80 * (1 - mask) + (0.22 + 0.28 * (1 - v)) * mask, 0.05, 1.0)
    return mask, rough


def enhance(path, modo="Dorado y bronce", fuerza=1.0, saturar=False, mapas_dir=None, log=print):
    """Reescribe el GLB con material PBR. Devuelve imagen de máscara (blanco = metal) o None."""
    mesh = trimesh.load(path, force="mesh", process=False)
    img = _texture(mesh)
    if img is None or not hasattr(mesh.visual, "uv") or mesh.visual.uv is None:
        log("El modelo no trae textura de color: no se pueden crear mapas de metal.")
        return None
    rgb = img.convert("RGB")
    if saturar:
        rgb = ImageEnhance.Contrast(ImageEnhance.Color(rgb).enhance(1.15)).enhance(1.05)
    mask, rough = make_maps(rgb, modo, fuerza)
    h, w = mask.shape
    mr = np.zeros((h, w, 3), np.uint8)
    mr[..., 0] = 255
    mr[..., 1] = (rough * 255).astype(np.uint8)
    mr[..., 2] = (mask * 255).astype(np.uint8)
    mat = trimesh.visual.material.PBRMaterial(
        baseColorTexture=rgb, metallicRoughnessTexture=Image.fromarray(mr, "RGB"),
        metallicFactor=1.0, roughnessFactor=1.0, name="forge_pbr")
    mesh.visual = trimesh.visual.TextureVisuals(uv=mesh.visual.uv, material=mat)
    mesh.export(path)
    mask_img = Image.fromarray((mask * 255).astype(np.uint8), "L")
    pct = 100.0 * float((mask > 0.5).mean())
    log(f"Material PBR aplicado: {pct:.1f}% de la textura detectada como metal")
    if mapas_dir:
        os.makedirs(mapas_dir, exist_ok=True)
        rgb.save(os.path.join(mapas_dir, "color.png"))
        mask_img.save(os.path.join(mapas_dir, "metalness.png"))
        Image.fromarray((rough * 255).astype(np.uint8), "L").save(os.path.join(mapas_dir, "roughness.png"))
        log("Mapas para Roblox (SurfaceAppearance) guardados en: " + mapas_dir)
    return mask_img
