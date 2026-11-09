"""(Solo para quien publica) genera manifest.json con los hashes de los archivos de código."""
import os, json, hashlib, sys
BASE = os.path.dirname(os.path.abspath(__file__))
CODIGO = ["app.py", "engines.py", "materials.py", "parts.py", "templates.py", "analysis.py", "ajustes.py",
          "actualizador.py", "optimize.py", "motor_luau.lua", "conocimiento_roblox.md", "requirements.txt"]
REQS = ["gradio", "gradio_client", "trimesh", "numpy", "pillow", "fast-simplification", "pymeshlab", "rembg[cpu]", "scipy"]
version = sys.argv[1] if len(sys.argv) > 1 else "1"
archivos = {n: hashlib.sha256(open(os.path.join(BASE, n), "rb").read()).hexdigest() for n in CODIGO}
json.dump({"version": version, "archivos": archivos, "requirements": REQS}, open(os.path.join(BASE, "manifest.json"), "w"), indent=1)
print("manifest.json listo,", len(archivos), "archivos")
