# Actualiza la API en el servidor Windows (EC2) desde GitHub, sin copiar archivos a mano.
#
# Uso (PowerShell como Administrador, dentro del servidor):
#   powershell -ExecutionPolicy Bypass -File C:\vehiculo_oit\deploy\actualizar_servidor.ps1
# Opciones:
#   -ControlAbierto si   -> mover y DEMO sin clave (CONTROL_ABIERTO=true en .env)
#   -ControlAbierto no   -> todo vuelve a pedir clave (CONTROL_ABIERTO=false)
#   (sin -ControlAbierto no se toca ese valor)
#
# Que hace:
#   1. Si la carpeta aun no es un repositorio git (antes se copiaban archivos), hace un
#      respaldo y la conecta a GitHub. El .env, el .venv y los registros NO se tocan.
#   2. Descarga la ultima version de la rama main (git fetch + reset): el servidor queda
#      identico a GitHub.
#   3. Reinstala dependencias solo si cambio requirements.txt.
#   4. Ajusta CONTROL_ABIERTO en .env si se pidio (sin mostrar el contenido del .env).
#   5. Reinicia la tarea VehiculoAPI y comprueba /health, /health/db y /sesion.
param(
    [string]$ProyectoDir = "C:\vehiculo_oit",
    [string]$Repo = "https://github.com/JuanArmando30/Examen_IoT_T2.git",
    [string]$Rama = "main",
    [ValidateSet("", "si", "no")][string]$ControlAbierto = "",
    [string]$Tarea = "VehiculoAPI"
)
# "Continue": git escribe avisos normales en stderr; los errores reales se revisan con $LASTEXITCODE.
$ErrorActionPreference = "Continue"
function Paso($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }
function Ok($t) { Write-Host "OK  $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "!!  $t" -ForegroundColor Yellow }

# --- 0. Requisitos ---------------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Abre PowerShell como Administrador y vuelve a ejecutar este script." -ForegroundColor Red; exit 1 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git no esta instalado en el servidor." -ForegroundColor Red
    Write-Host "Instalalo una sola vez desde https://git-scm.com/download/win (opciones por defecto),"
    Write-Host "cierra y abre PowerShell como Administrador y vuelve a ejecutar este script."
    exit 1
}
if (-not (Test-Path $ProyectoDir)) { Write-Host "No existe $ProyectoDir" -ForegroundColor Red; exit 1 }
Set-Location $ProyectoDir
# Evita el error "dubious ownership" si la carpeta la creo otro usuario.
$dirGit = $ProyectoDir.Replace('\', '/')
if (-not (@(git config --global --get-all safe.directory) -contains $dirGit)) {
    git config --global --add safe.directory $dirGit
}
$python = Join-Path $ProyectoDir ".venv\Scripts\python.exe"

# --- 1. Conectar la carpeta con GitHub (solo la primera vez) -----------------------
Paso "1. Repositorio"
if (-not (Test-Path (Join-Path $ProyectoDir ".git"))) {
    $respaldo = "$ProyectoDir" + "_respaldo_" + (Get-Date -Format "yyyyMMdd_HHmmss")
    Aviso "La carpeta no es un repositorio git (se actualizaba copiando archivos)."
    Write-Host "Respaldo del codigo actual en $respaldo (sin .venv) ..."
    robocopy $ProyectoDir $respaldo /E /XD .venv __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
    git init -q
    git remote add origin $Repo
    Ok "Carpeta conectada a $Repo"
} else {
    $url = (git remote get-url origin 2>$null)
    if ($url -ne $Repo) { git remote set-url origin $Repo; Ok "Origen actualizado a $Repo" } else { Ok "Repositorio git: $url" }
}

# --- 2. Descargar la ultima version -----------------------------------------------
Paso "2. Descargar cambios de GitHub ($Rama)"
$reqAntes = if (Test-Path requirements.txt) { (Get-FileHash requirements.txt).Hash } else { "" }
$antes = (git rev-parse --verify -q HEAD 2>$null)
git fetch -q origin $Rama
if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo descargar de GitHub (revisa la conexion a internet del servidor)." -ForegroundColor Red; exit 1 }
$cambios = if ($antes) { git log --oneline "$antes..origin/$Rama" } else { git log --oneline -5 "origin/$Rama" }
# Deja los archivos versionados identicos a GitHub. .env, .venv y *.log estan en .gitignore: no se tocan.
git reset -q --hard "origin/$Rama"
git checkout -q -B $Rama "origin/$Rama"
if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo dejar la carpeta igual a GitHub (git reset/checkout)." -ForegroundColor Red; exit 1 }
if ($cambios) { Write-Host "Cambios aplicados:"; $cambios | ForEach-Object { "   $_" } } else { Ok "Ya estaba al dia" }
Ok ("Version actual: " + (git log --oneline -1))

# --- 3. Dependencias ---------------------------------------------------------------
Paso "3. Dependencias"
if (-not (Test-Path $python)) {
    Aviso "No existe .venv: se crea."
    python -m venv .venv
    $reqAntes = "forzar"
}
if ((Get-FileHash requirements.txt).Hash -ne $reqAntes) {
    & $python -m pip install -q -r requirements.txt
    Ok "Dependencias instaladas"
} else { Ok "requirements.txt sin cambios" }

# --- 4. CONTROL_ABIERTO en .env ----------------------------------------------------
Paso "4. Control sin clave (CONTROL_ABIERTO)"
$envFile = Join-Path $ProyectoDir ".env"
if (-not (Test-Path $envFile)) { Write-Host "Falta el archivo .env en $ProyectoDir" -ForegroundColor Red; exit 1 }
if ($ControlAbierto) {
    $valor = if ($ControlAbierto -eq "si") { "true" } else { "false" }
    $lineas = @(Get-Content $envFile)
    if ($lineas -match '^\s*CONTROL_ABIERTO\s*=') {
        $lineas = $lineas -replace '^\s*CONTROL_ABIERTO\s*=.*$', "CONTROL_ABIERTO=$valor"
    } else {
        $lineas += "CONTROL_ABIERTO=$valor"
    }
    # UTF-8 sin BOM (python-dotenv lo lee sin problemas)
    [IO.File]::WriteAllLines($envFile, [string[]]$lineas, (New-Object Text.UTF8Encoding($false)))
    Ok "CONTROL_ABIERTO=$valor"
} else {
    $actual = (Select-String -Path $envFile -Pattern '^\s*CONTROL_ABIERTO\s*=\s*(.*)$' | Select-Object -First 1)
    if ($actual) { Ok ("Sin cambios: CONTROL_ABIERTO=" + $actual.Matches[0].Groups[1].Value.Trim()) } else { Ok "Sin cambios: CONTROL_ABIERTO no definido (= false)" }
}

# --- 5. Reiniciar la API ---------------------------------------------------------
Paso "5. Reiniciar la API (tarea $Tarea)"
if (-not (Get-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue)) {
    Write-Host "No existe la tarea programada '$Tarea'. Revisa el nombre con: Get-ScheduledTask | Select TaskName" -ForegroundColor Red
    exit 1
}
Stop-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue
# Solo los procesos de Uvicorn de esta API (no otros Python del servidor).
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like "*uvicorn*app.main*" -or $_.ExecutablePath -like "$ProyectoDir\.venv\*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $Tarea
Ok "Tarea iniciada"

Paso "6. Comprobacion"
$listo = $false
for ($i = 0; $i -lt 20 -and -not $listo; $i++) {
    Start-Sleep -Seconds 1
    try { $null = Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 3; $listo = $true } catch { }
}
if (-not $listo) {
    Write-Host "La API no responde en http://127.0.0.1:8000/health. Ultimas lineas de api.log:" -ForegroundColor Red
    if (Test-Path "$ProyectoDir\api.log") { Get-Content "$ProyectoDir\api.log" -Tail 25 }
    exit 1
}
Ok "/health responde"
try { $null = Invoke-RestMethod http://127.0.0.1:8000/health/db -TimeoutSec 8; Ok "/health/db: RDS disponible" } catch { Aviso "/health/db fallo: revisa RDS (no impide el arranque)" }
try {
    $s = Invoke-RestMethod http://127.0.0.1:8000/sesion -TimeoutSec 3
    Ok "Control ABIERTO: mover y DEMO sin clave (crear/editar/eliminar siguen pidiendo clave) -> $($s | ConvertTo-Json -Compress)"
} catch {
    Ok "Control CERRADO: todo pide la clave X-API-Key (GET /sesion sin clave = 401)"
}
Write-Host ""
Write-Host "Listo. Prueba publica: https://vehiculos-juan.duckdns.org/health" -ForegroundColor Green
