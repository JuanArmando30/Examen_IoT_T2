# Diagnostico rapido del servidor Windows (EC2). Ejecutar como Administrador:
#   powershell -ExecutionPolicy Bypass -File C:\vehiculo_oit\deploy\windows\diagnostico_servidor.ps1
param([string]$ProyectoDir = "C:\vehiculo_oit", [string]$Dominio = "vehiculos-juan.duckdns.org")

function Titulo($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }

Titulo "1. Arranque del servidor"
$so = Get-CimInstance Win32_OperatingSystem
"Ultimo arranque: $($so.LastBootUpTime)"
"Hora actual:     $(Get-Date)"

Titulo "2. Eventos recientes de apagado/reinicio (por que se apago Windows)"
# 1074 = apagado o reinicio solicitado | 6006 = apagado limpio | 6008 = apagado inesperado | 41 = reinicio sin apagado limpio
Get-WinEvent -FilterHashtable @{LogName = 'System'; Id = 41, 1074, 6006, 6008} -MaxEvents 8 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, Id, @{n = 'Detalle'; e = { ($_.Message -split "`n")[0] } } | Format-Table -AutoSize -Wrap

Titulo "3. Tareas programadas (API y Caddy)"
Get-ScheduledTask -TaskName "VehiculoAPI", "VehiculoCaddy" -ErrorAction SilentlyContinue | Format-Table TaskName, State
foreach ($n in "VehiculoAPI", "VehiculoCaddy") {
    $i = Get-ScheduledTaskInfo -TaskName $n -ErrorAction SilentlyContinue
    if ($i) { "$n -> ultima ejecucion: $($i.LastRunTime)  resultado: $($i.LastTaskResult)" }
}
Write-Host "Otras tareas activas que podrian apagar el equipo:"
Get-ScheduledTask | Where-Object { $_.State -ne "Disabled" -and $_.TaskPath -notlike "\Microsoft\*" } |
    Select-Object TaskName, TaskPath, State | Format-Table -AutoSize

Titulo "4. Puertos en escucha (80 y 443 = Caddy, 8000 = API local)"
Get-NetTCPConnection -State Listen -LocalPort 80, 443, 8000 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize

Titulo "5. Espacio en disco C:"
$c = Get-PSDrive C
"Usado: {0:N1} GB   Libre: {1:N1} GB" -f ($c.Used / 1GB), ($c.Free / 1GB)

Titulo "6. Salud de la API (local)"
try { "health:    " + (Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Compress) } catch { Write-Host "health: NO responde" -ForegroundColor Red }
try { "health/db: " + (Invoke-RestMethod http://127.0.0.1:8000/health/db | ConvertTo-Json -Compress) } catch { Write-Host "health/db: FALLA (RDS apagado, sin acceso o regla 3306)" -ForegroundColor Red }

Titulo "7. IP publica del servidor vs DNS"
$ipPublica = $null
try { $ipPublica = (Invoke-RestMethod https://checkip.amazonaws.com).ToString().Trim(); "IP publica actual del servidor: $ipPublica" } catch { Write-Host "No se pudo consultar la IP publica" -ForegroundColor Yellow }
try {
    $dns = (Resolve-DnsName $Dominio -Type A -ErrorAction Stop | Where-Object { $_.Type -eq 'A' }).IPAddress
    "DNS de ${Dominio}: $dns"
    if ($ipPublica -and ($dns -notcontains $ipPublica)) { Write-Host "ATENCION: el DNS NO apunta a la IP publica actual. Actualiza DuckDNS." -ForegroundColor Red }
    else { Write-Host "El DNS coincide con la IP del servidor." -ForegroundColor Green }
} catch { Write-Host "No se pudo resolver $Dominio" -ForegroundColor Yellow }

Titulo "8. Ultimas lineas de los registros"
"--- api.log ---";   if (Test-Path "$ProyectoDir\api.log")  { Get-Content "$ProyectoDir\api.log" -Tail 12 }  else { "(no existe)" }
"--- caddy.log ---"; if (Test-Path "C:\caddy\caddy.log")    { Get-Content "C:\caddy\caddy.log" -Tail 8 }     else { "(no existe)" }
