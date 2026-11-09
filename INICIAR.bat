@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ForgeMesh

if not exist "app.py" (
  echo.
  echo ERROR: abriste este archivo dentro del ZIP. Cierra esta ventana,
  echo haz clic derecho en ForgeMesh.zip, elige "Extraer todo" y abre INICIAR.bat desde la carpeta extraida.
  pause
  exit /b 1
)

set "PY="
if exist "venv\Scripts\python.exe" goto :tengo_venv

rem --- buscar Python ---
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"

if not defined PY (
  echo Instalando Python automaticamente, espera...
  winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
  if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
)
if not defined PY (
  echo.
  echo No pude instalar Python solo. Instalalo desde python.org marcando "Add python.exe to PATH" y vuelve a abrir este archivo.
  pause
  exit /b 1
)

echo Creando entorno...
%PY% -m venv venv
if not exist "venv\Scripts\python.exe" (
  echo Fallo al crear el entorno. Copia este mensaje y pegaselo a Claude.
  pause
  exit /b 1
)

:tengo_venv
if not exist "venv\listo.txt" (
  echo Instalando dependencias, tarda unos minutos, no cierres la ventana...
  "venv\Scripts\python.exe" -m pip install --upgrade pip
  "venv\Scripts\python.exe" -m pip install gradio gradio_client trimesh numpy pillow fast-simplification
  if errorlevel 1 (
    echo Fallo la instalacion. Copia este mensaje y pegaselo a Claude.
    pause
    exit /b 1
  )
  "venv\Scripts\python.exe" -m pip install pymeshlab
  "venv\Scripts\python.exe" -m pip install "rembg[cpu]"
  echo ok> "venv\listo.txt"
)

echo Buscando actualizaciones...
"venv\Scripts\python.exe" actualizador.py
echo Abriendo ForgeMesh en el navegador...
"venv\Scripts\python.exe" app.py
pause
