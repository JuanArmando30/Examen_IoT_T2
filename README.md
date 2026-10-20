# API Vehículo IoT

API hecha con **Python y FastAPI** para controlar y monitorear un vehículo IoT (por ejemplo, una excavadora controlada por un ESP8266/ESP32). Guarda sus datos en una base MySQL alojada en **Amazon RDS** y usa únicamente **procedimientos almacenados** (21 en total) para leer y escribir.

Este proyecto nació en la **Práctica 2.5** (entorno local, `http://localhost:8000`) y se publicó en AWS en el **Examen 2.6**: la API corre en Amazon EC2, con HTTPS/WSS, y usa la base de datos en Amazon RDS.

---

## Despliegue público en AWS (Examen 2.6)

| Qué | Dirección |
|---|---|
| API | https://vehiculos-juan.duckdns.org |
| Swagger UI (documentación) | https://vehiculos-juan.duckdns.org/docs |
| Salud de la API y de RDS | https://vehiculos-juan.duckdns.org/health/db |
| WebSocket seguro (WSS) | `wss://vehiculos-juan.duckdns.org/ws/vehiculos/{id_vehiculo}` |

### Cómo está publicada

```
Cliente ──HTTPS/WSS (443)──► Caddy ──► Uvicorn (127.0.0.1:8000) ──► Amazon RDS (3306)
                          └─────── Amazon EC2 (Windows Server) ───────┘
```

- **Amazon EC2 (Windows Server)** con IP elástica. Su grupo de seguridad solo abre 80 y 443 al público; el escritorio remoto (3389) está limitado a mi IP y el puerto 8000 **no** se expone.
- **DuckDNS** da el dominio gratuito que apunta a la IP elástica.
- **Caddy** recibe HTTPS/WSS, obtiene y renueva solo el certificado de Let's Encrypt, redirige HTTP a HTTPS y pasa el tráfico a Uvicorn.
- **Uvicorn** escucha únicamente en `127.0.0.1:8000`.
- **Amazon RDS** solo acepta el puerto 3306 desde el grupo de seguridad de la instancia EC2.
- Dos **tareas programadas de Windows** (`VehiculoAPI` y `VehiculoCaddy`) arrancan con el servidor y se reinician solas si fallan, así que la API sigue funcionando aunque se cierre cualquier sesión.

Los archivos de despliegue están en la carpeta `deploy/` (`deploy/windows/registrar_tareas.ps1` y `deploy/Caddyfile.example`). El `.env` solo existe en el servidor y nunca se sube a GitHub.

### Instalar en el servidor (resumen)

```powershell
git clone https://github.com/JuanArmando30/vehiculo_oit.git C:\vehiculo_oit
cd C:\vehiculo_oit
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# crear C:\vehiculo_oit\.env con los datos de RDS y claves nuevas
.\.venv\Scripts\python.exe -m app.db.verificar_procedimientos
powershell -ExecutionPolicy Bypass -File .\deploy\windows\registrar_tareas.ps1
```

### Actualizar el servidor después de un cambio

```powershell
cd C:\vehiculo_oit
Stop-ScheduledTask VehiculoAPI
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
git pull
Start-ScheduledTask VehiculoAPI
```

### Probar por HTTPS/WSS

| Antes (local) | Ahora (público) |
|---|---|
| `http://localhost:8000/...` | `https://vehiculos-juan.duckdns.org/...` |
| `ws://localhost:8000/ws/vehiculos/1` | `wss://vehiculos-juan.duckdns.org/ws/vehiculos/1` |

---

## ¿Qué hace la API?

- **Administra vehículos**, el **catálogo de comandos** de cada uno (AVANZAR, RETROCEDER, DETENER…) y su **último estado**.
- **Ejecuta un movimiento individual**: valida la orden, actualiza el estado, la guarda en el historial y avisa en tiempo real por WebSocket.
- **Ejecuta una DEMO**: una secuencia de N movimientos configurada en la base de datos, que se transmite por WebSocket respetando la duración y la pausa de cada paso.
- **Consulta el historial**: devuelve como máximo los 10 movimientos individuales más recientes.
- **Documenta todo en Swagger UI** (`/docs`).

La regla más importante del proyecto:

> Los movimientos **individuales** se guardan en el historial. Los movimientos de una **DEMO** **no** se guardan en el historial: solo se transmiten por WebSocket y actualizan el último comando del vehículo.

---

## Tecnologías

| Herramienta | Para qué se usa |
|---|---|
| Python 3.14 | Lenguaje de programación |
| FastAPI + Uvicorn | Servidor web y endpoints (HTTP y WebSocket) |
| Pydantic | Validación de los datos de entrada y salida |
| mysql-connector-python | Conexión a MySQL / Amazon RDS |
| python-dotenv | Lectura de variables de entorno desde `.env` |
| Amazon RDS (MySQL) | Base de datos `vehiculo_iot` |
| Thunder Client | Pruebas de la API desde Visual Studio Code |

---

## Cómo ejecutarla en tu computadora

### 1. Requisitos previos
- Python 3 instalado.
- Visual Studio Code (recomendado) con la extensión Thunder Client.
- La base `vehiculo_iot` ya creada en Amazon RDS, con sus tablas y sus 21 procedimientos almacenados (prácticas 2.3 y 2.4).
- El Security Group de RDS con una regla **MySQL/Aurora (TCP 3306)** cuyo origen sea **tu IP actual** (opción *My IP*). Si tu IP cambia, hay que actualizar la regla.

### 2. Clonar el repositorio
```powershell
git clone https://github.com/JuanArmando30/vehiculo_oit.git
cd vehiculo_oit
```

### 3. Crear y activar el entorno virtual
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```
Sabrás que está activo porque el prompt empieza con `(.venv)`. Si PowerShell bloquea el script, ejecuta una sola vez:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 4. Instalar las dependencias
```powershell
pip install -r requirements.txt
```

### 5. Configurar las variables de entorno
Copia el archivo de ejemplo y edítalo con tus datos reales:
```powershell
copy .env.example .env
```

| Variable | Qué significa |
|---|---|
| `DB_HOST` | Endpoint de tu instancia RDS |
| `DB_PORT` | Puerto de MySQL (3306) |
| `DB_NAME` | Nombre de la base: `vehiculo_iot` |
| `DB_USER` / `DB_PASSWORD` | Usuario y contraseña de MySQL |
| `API_KEY_OPERADOR` | Clave para crear, actualizar y controlar (movimientos y DEMO) |
| `API_KEY_ADMIN` | Clave para además eliminar registros |

Las dos claves de la API deben tener al menos 12 caracteres y ser distintas. Puedes generarlas así:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

> ⚠️ El archivo `.env` contiene secretos y **nunca se sube a GitHub** (está en `.gitignore`). Solo se sube `.env.example`, que tiene valores de relleno.

### 6. Verificar la conexión y los 21 procedimientos
```powershell
python -m app.db.verificar_procedimientos
```
Debe terminar con `OK: los 21 procedimientos almacenados existen.`

### 7. Arrancar el servidor
```powershell
uvicorn app.main:app --reload --port 8000
```

| Qué | Dirección |
|---|---|
| API | http://localhost:8000 |
| Swagger UI (documentación interactiva) | http://localhost:8000/docs |
| Salud de la API | http://localhost:8000/health |
| Salud de la conexión a RDS | http://localhost:8000/health/db |

---

## Cómo se organiza el código

```
app/
├── main.py              Arranque de la app, manejo de errores y registro de routers
├── contenedor.py        Crea y conecta todos los componentes al iniciar
├── core/
│   ├── config.py        Lee y valida las variables del .env
│   ├── exceptions.py    Errores de negocio (404, 409, 503, etc.)
│   └── security.py      Identifica el rol según la clave X-API-Key
├── db/
│   ├── database.py      Abre conexiones a RDS y maneja transacciones
│   └── verificar_procedimientos.py   Comprueba que existan los 21 SP
├── repositories/
│   └── stored_procedure_repository.py   Un método por cada procedimiento almacenado
├── services/            Reglas de negocio
│   ├── vehiculo_service.py, comando_service.py, estado_service.py
│   ├── historial_service.py, movimiento_service.py, demo_service.py
│   └── demo_ejecutor.py Ejecuta las DEMO de forma asíncrona
├── websocket/
│   ├── gestor.py        Controla los clientes conectados a cada vehículo
│   └── eventos.py       Arma los mensajes JSON que se envían
├── models/schemas.py    Modelos de entrada y salida (validación y Swagger)
└── api/
    ├── dependencies.py  Seguridad y parámetros compartidos
    ├── documentacion.py Textos y respuestas de error para Swagger
    └── routes/          Endpoints HTTP y WebSocket
```

La idea es que cada capa haga una sola cosa:
- **Los endpoints** reciben la petición y responden; no tocan la base de datos.
- **Los servicios** deciden si algo es válido (¿existe el vehículo? ¿está activo? ¿el comando es de ese vehículo?).
- **El repositorio** es el único que conoce los procedimientos almacenados y siempre los ejecuta con parámetros enlazados (nunca arma SQL concatenando texto).

---

## Autenticación

Las consultas (GET) son libres. Todo lo que **escribe o controla** necesita la cabecera `X-API-Key`:

| Operación | Clave necesaria |
|---|---|
| GET (consultas) | Ninguna |
| POST de crear, actualizar, movimientos, iniciar/cancelar DEMO | `API_KEY_OPERADOR` (o la de admin) |
| POST de `.../eliminar` | `API_KEY_ADMIN` |

Sin clave o con clave incorrecta responde **401**. Con la clave de operador en una operación de eliminar responde **403**.

En Swagger UI pulsa **Authorize** y pega la clave; en Thunder Client agrega la cabecera `X-API-Key`.

---

## Cómo funcionan los dos tipos de movimiento

### Movimiento individual
`POST /vehiculos/{id}/movimientos`

1. La API verifica que el vehículo exista y esté activo.
2. Verifica que el comando exista, esté activo y **pertenezca a ese vehículo** (un comando de otro vehículo se rechaza).
3. En **una sola transacción** ejecuta `sp_actualizar_estado` y `sp_registrar_historial`. O se guardan las dos cosas o ninguna.
4. Cuando la transacción ya se confirmó en RDS, avisa por WebSocket a los clientes conectados a ese vehículo.

Si algo falla en los pasos 1 a 3, no se cambia el estado, no se escribe el historial y no se emite ningún evento.

El campo `conectado` **no** se vuelve verdadero solo porque llegó una petición HTTP: la API conserva el valor que ya tenía.

Ejemplo de cuerpo (puedes enviar `id_comando` **o** `codigo`, uno solo):
```json
{ "id_comando": 1, "origen": "THUNDER_CLIENT" }
```

### DEMO
`POST /vehiculos/{id}/demos/{id_demo}/iniciar`

1. La API responde de inmediato **202 Accepted** y sigue trabajando en segundo plano.
2. Lee de RDS los N movimientos de la DEMO con `sp_obtener_movimientos_demo` (no hay ninguna secuencia fija en el código).
3. Por cada movimiento, en orden: actualiza el último comando con `sp_actualizar_estado`, envía el evento por WebSocket, espera `duracion_ms` y luego `pausa_ms`.
4. **No** usa `sp_registrar_historial`.

Reglas de seguridad de la DEMO:
- Solo una DEMO a la vez por vehículo (la segunda recibe **409**).
- Mientras una DEMO corre, no se aceptan movimientos individuales para ese vehículo (409).
- Se puede cancelar con `POST /vehiculos/{id}/demos/cancelar`: se detiene al instante, el vehículo queda en `DETENER` (si existe ese comando) y se avisa con el evento `demo_cancelada`.
- Si falla RDS o ocurre un error, la secuencia termina de forma controlada y se envía un evento `error`.

Con los datos de ejemplo del proyecto la DEMO dura alrededor de 12 segundos (8 movimientos).

### Historial
`GET /vehiculos/{id}/historial` devuelve **como máximo 10** movimientos individuales, del más reciente al más antiguo. Si hay menos de 10, devuelve los que existan; si no hay ninguno, devuelve una lista vacía (200); si el vehículo no existe, 404. El historial completo se conserva en RDS.

---

## Endpoints HTTP

La guía de la práctica pide **GET para consultar** y **POST para escribir, actualizar y ejecutar acciones**, por eso las actualizaciones y eliminaciones también usan POST.

| Método | Ruta | Qué hace | Procedimientos |
|---|---|---|---|
| GET | `/vehiculos` | Lista los vehículos | `sp_obtener_vehiculos` |
| POST | `/vehiculos` | Crea un vehículo | `sp_crear_vehiculo` |
| GET | `/vehiculos/{id}` | Detalle: vehículo + comandos + último estado + DEMO | `sp_obtener_vehiculo`, `sp_obtener_comandos_vehiculo`, `sp_obtener_estado`, `sp_obtener_demos` |
| POST | `/vehiculos/{id}/actualizar` | Actualiza un vehículo | `sp_actualizar_vehiculo` |
| POST | `/vehiculos/{id}/eliminar` 🔒admin | Elimina un vehículo | `sp_eliminar_vehiculo` |
| GET | `/vehiculos/{id}/comandos` | Catálogo de comandos | `sp_obtener_comandos_vehiculo` |
| POST | `/vehiculos/{id}/comandos` | Agrega un comando al catálogo | `sp_crear_comando` |
| POST | `/vehiculos/{id}/comandos/{id_comando}/actualizar` | Actualiza un comando | `sp_actualizar_comando` |
| POST | `/vehiculos/{id}/comandos/{id_comando}/eliminar` 🔒admin | Elimina un comando | `sp_eliminar_comando` |
| GET | `/vehiculos/{id}/estado` | Último estado registrado | `sp_obtener_estado` |
| POST | `/vehiculos/{id}/estado` | Cambia `conectado` (sin tocar el historial) | `sp_actualizar_estado` |
| GET | `/vehiculos/{id}/historial` | Últimos 10 movimientos individuales | `sp_obtener_historial` |
| POST | `/vehiculos/{id}/movimientos` | **Movimiento individual** | `sp_actualizar_estado` + `sp_registrar_historial` |
| GET | `/vehiculos/{id}/demos` | Lista las DEMO | `sp_obtener_demos` |
| POST | `/vehiculos/{id}/demos` | Crea una DEMO | `sp_crear_demo` |
| POST | `/vehiculos/{id}/demos/{id_demo}/actualizar` | Actualiza una DEMO | `sp_actualizar_demo` |
| POST | `/vehiculos/{id}/demos/{id_demo}/eliminar` 🔒admin | Elimina una DEMO | `sp_eliminar_demo` |
| GET | `/vehiculos/{id}/demos/{id_demo}/movimientos` | Movimientos ordenados de la DEMO | `sp_obtener_movimientos_demo` |
| POST | `/vehiculos/{id}/demos/{id_demo}/movimientos` | Agrega un movimiento a la DEMO | `sp_agregar_movimiento_demo` |
| POST | `.../movimientos/{id_mov}/actualizar` | Actualiza un movimiento de la DEMO | `sp_actualizar_movimiento_demo` |
| POST | `.../movimientos/{id_mov}/eliminar` 🔒admin | Elimina un movimiento de la DEMO | `sp_eliminar_movimiento_demo` |
| POST | `/vehiculos/{id}/demos/{id_demo}/iniciar` | **Inicia una DEMO** (202) | `sp_obtener_movimientos_demo`, `sp_actualizar_estado` |
| POST | `/vehiculos/{id}/demos/cancelar` | Cancela la DEMO en curso | `sp_actualizar_estado` |
| GET | `/vehiculos/{id}/demos/ejecucion` | ¿Hay una DEMO corriendo? | — |
| GET | `/`, `/health`, `/health/db` | Estado de la API y de RDS | — |

Con esto quedan integrados los **21 procedimientos almacenados**.

### Códigos de respuesta
| Código | Cuándo |
|---|---|
| 200 | Consulta o acción correcta |
| 201 | Registro creado (por ejemplo, un movimiento) |
| 202 | DEMO aceptada; se ejecuta en segundo plano |
| 400 | Referencia inexistente o valor fuera de rango |
| 401 | Falta la clave o es incorrecta |
| 403 | La clave no tiene permiso de administrador |
| 404 | Vehículo, comando, DEMO o movimiento inexistente |
| 409 | Conflicto: duplicado, elemento inactivo, DEMO en curso, recurso en uso |
| 422 | El cuerpo o los parámetros no cumplen la validación |
| 500 | Error interno (sin mostrar datos sensibles) |
| 503 | Amazon RDS no disponible |

---

## WebSocket

Swagger UI no describe WebSocket, así que se documenta aquí.

**URL pública (WSS):** `wss://vehiculos-juan.duckdns.org/ws/vehiculos/{id_vehiculo}`

**URL local:** `ws://localhost:8000/ws/vehiculos/{id_vehiculo}`

Por ejemplo: `wss://vehiculos-juan.duckdns.org/ws/vehiculos/1`

Cómo se comporta:
- Al conectarte recibes enseguida el **último estado** del vehículo (`estado_inicial`).
- Después recibes **solo** los eventos del vehículo que estás monitoreando.
- Pueden conectarse varios clientes al mismo vehículo a la vez. Si uno falla o se desconecta, los demás no se afectan.
- Si envías el texto `ping`, la API responde con un evento `pong`.
- Si el vehículo no existe, recibes un evento `error` y la conexión se cierra con el código `4404`.

### Formato de todos los mensajes
```json
{
  "evento": "demo_movimiento",
  "id_vehiculo": 1,
  "comando": "AVANZAR",
  "codigo": 1,
  "timestamp": "2026-10-15T18:30:00.123456+00:00",
  "datos": { }
}
```
`comando` y `codigo` son `null` cuando el evento no se refiere a un comando. `timestamp` está en UTC. Lo específico de cada evento va dentro de `datos`.

### Eventos

| Evento | Cuándo llega | Qué trae `datos` |
|---|---|---|
| `estado_inicial` | Al conectarte | `conectado`, `fecha_actualizacion` |
| `estado_actualizado` | Cuando se cambia el estado con `POST .../estado` | `conectado`, `fecha_actualizacion` |
| `movimiento_individual` | Después de confirmar en RDS un movimiento individual | `origen`, `conectado`, `fecha_actualizacion`, `registrado_en_historial: true` |
| `demo_iniciada` | Empieza una DEMO | `id_demo`, `nombre`, `total_movimientos`, `duracion_estimada_ms` |
| `demo_movimiento` | Uno por cada movimiento de la DEMO, en orden | `id_demo`, `orden`, `total_movimientos`, `duracion_ms`, `pausa_ms`, `registrado_en_historial: false` |
| `demo_finalizada` | La DEMO terminó normalmente | `id_demo`, `movimientos_ejecutados` |
| `demo_cancelada` | Se canceló la DEMO | `id_demo`, `movimientos_ejecutados`, `detenido_con` |
| `error` | Falló RDS o los datos, o se rechazó la conexión | `codigo_error`, `detalle` |
| `pong` | Respuesta a `ping` | — |

### Ejemplos

Movimiento de una DEMO:
```json
{
  "evento": "demo_movimiento",
  "id_vehiculo": 1,
  "comando": "AVANZAR",
  "codigo": 1,
  "timestamp": "2026-10-15T18:30:00.123456+00:00",
  "datos": {
    "id_demo": 1,
    "orden": 1,
    "total_movimientos": 8,
    "duracion_ms": 2000,
    "pausa_ms": 400,
    "registrado_en_historial": false
  }
}
```

Cancelación:
```json
{
  "evento": "demo_cancelada",
  "id_vehiculo": 1,
  "comando": "DETENER",
  "codigo": 9,
  "timestamp": "2026-10-15T18:30:05.000000+00:00",
  "datos": { "id_demo": 1, "movimientos_ejecutados": 3, "detenido_con": "DETENER" }
}
```

Error:
```json
{
  "evento": "error",
  "id_vehiculo": 1,
  "comando": null,
  "codigo": null,
  "timestamp": "2026-10-15T18:30:07.000000+00:00",
  "datos": { "codigo_error": "DEMO_ERROR", "detalle": "La DEMO se detuvo por un error interno.", "id_demo": 1 }
}
```

> Un mensaje enviado por WebSocket **no confirma** que el vehículo haya ejecutado el movimiento. La confirmación del microcontrolador (ESP8266/ESP32) se integrará en una práctica posterior.

---

## Las tres pruebas funcionales (Thunder Client)

Todos los POST llevan la cabecera `X-API-Key`.

**Prueba 1 – POST de movimiento individual**
`POST http://localhost:8000/vehiculos/1/movimientos` con `{"id_comando": 1, "origen": "THUNDER_CLIENT"}`. Debe responder 201. Luego comprueba que `estado_vehiculo` refleja el comando y que `historial_comandos` tiene un registro nuevo.

**Prueba 2 – GET del historial**
`GET http://localhost:8000/vehiculos/1/historial`. Con más de 10 registros en RDS, devuelve exactamente 10, del más reciente al más antiguo. Con menos de 10, devuelve solo los disponibles.

**Prueba 3 – WebSocket + DEMO**
1. Conéctate a `ws://localhost:8000/ws/vehiculos/1`.
2. Anota cuántos registros tiene `historial_comandos`.
3. Envía `POST http://localhost:8000/vehiculos/1/demos/1/iniciar`.
4. Verás `demo_iniciada`, los N `demo_movimiento` en orden y `demo_finalizada`.
5. Vuelve a contar el historial: no debe haber cambiado.

---

## Seguridad y buenas prácticas aplicadas

- Las credenciales viven en variables de entorno; `.env` está excluido de Git.
- Los procedimientos se ejecutan con parámetros enlazados y desde una lista blanca de nombres.
- Los cambios relacionados (estado + historial) ocurren en una transacción atómica.
- Las operaciones de escritura, control y eliminación exigen autenticación; eliminar exige además rol de administrador.
- Los errores nunca muestran usuarios, hosts ni contraseñas: el detalle técnico queda solo en el log local.
- Las llamadas a MySQL se ejecutan fuera del bucle asíncrono para no bloquear a otros clientes ni conexiones WebSocket.

Recomendación opcional: crear en MySQL un usuario exclusivo para la API con solo el permiso de ejecutar procedimientos:
```sql
CREATE USER 'api_vehiculos'@'%' IDENTIFIED BY 'una_contraseña_segura';
GRANT EXECUTE ON vehiculo_iot.* TO 'api_vehiculos'@'%';
```

---

## Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `ModuleNotFoundError: No module named 'mysql'` | El entorno virtual no está activo o faltan dependencias | Activa `.venv` y ejecuta `pip install -r requirements.txt` |
| `Faltan variables en el archivo .env` | No existe `.env` o le faltan claves | Copia `.env.example` y complétalo |
| `/health/db` responde 503 | No hay conexión con RDS | Revisa que tu IP actual esté en el Security Group (puerto 3306) y que el endpoint sea correcto |
| 401 al hacer un POST | Falta `X-API-Key` o no coincide | Copia la clave exacta del `.env`, sin espacios; reinicia el servidor si cambiaste el `.env` |
| 403 al eliminar | Usaste la clave de operador | Usa `API_KEY_ADMIN` |
| 409 al iniciar una DEMO | Ya hay otra en curso, está inactiva o no tiene movimientos | Cancela la actual o revisa la DEMO |
| 409 al enviar un movimiento | Hay una DEMO corriendo en ese vehículo | Espera a que termine o cancélala |

---

## Qué cambió al publicarla en AWS

La lógica de la API se mantuvo; cambió el entorno: ahora corre en EC2 con dominio, HTTPS y WSS, el Security Group de RDS solo permite el acceso desde la instancia, y las claves viajan cifradas. Como mejora futura queda la autenticación del WebSocket y la confirmación del ESP8266/ESP32.

---

## Autor

Proyecto individual desarrollado por **Juan Armando Castillo Rodríguez** para la materia *Implementación de Soluciones IoT*.
