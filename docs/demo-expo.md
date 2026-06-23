# Demo de exposición (1 minuto) — uFlex Edge Gateway

Guion para mostrar en vivo el flujo **dato crudo en tiempo real → procesamiento en el edge → dato procesado** que consumiría el backend / móvil / web.

La idea visual: abrir Scalar, ejecutar los GET y verlos **vacíos**; levantar el Wokwi; volver a ejecutar los GET y ver **el crudo guardado** y **la data procesada**.

---

## 0. Conceptos (qué muestra cada cosa)

| Capa | Tabla | Endpoint para verla | Qué es |
|------|-------|---------------------|--------|
| **Crudo (real time)** | `movement_records` | `GET /api/v1/movement-monitoring/data-records` | Cada ángulo que envía el kit, tal cual entra. "Lo que guardamos." |
| **Procesado** | `serie_executions` | `GET /api/v1/movement-monitoring/series` | Resultado de la serie: reps buenas/malas, ROM, `valoracion`, movimiento peligroso. "Lo que consumiría el backend." |

El vínculo entre ambas es el **`serie_id`**: cada lectura cruda se estampa con el `serie_id` de la serie abierta, así puedes filtrar las dos tablas por el mismo valor.

> El dato crudo **ya no se borra** al cerrar la serie: queda guardado y vinculado a su `serie_id`, para poder mostrar crudo y procesado lado a lado.

---

## 1. Preparación (antes de la expo)

### 1.1 Base de datos limpia (opcional, recomendado para arrancar en cero)
Borra el archivo `uflex_edge.db`. Se regenera solo al primer request, con la columna `serie_id` y el kit de prueba resembrado (`uflex-kit-001` / `test-api-key-123`).

```powershell
Remove-Item .\uflex_edge.db -ErrorAction SilentlyContinue
```

> Si **no** lo borras, no pasa nada: al arrancar se aplica una migración automática que añade la columna `serie_id` sin perder datos.

### 1.2 Levantar el edge (Flask)
```powershell
.\.venv\Scripts\Activate.ps1
python -m app.main
```
Queda escuchando en `http://0.0.0.0:5050` (todas las interfaces, para que el ESP32/Wokwi alcance la laptop por su IP de LAN).

### 1.3 Saber la IP de la laptop (para el firmware del Wokwi)
```powershell
ipconfig   # busca la IPv4 de tu adaptador de red (ej. 192.168.x.x)
```
El firmware del Wokwi debe hacer POST a `http://<IP-laptop>:5050/api/v1/movement-monitoring/data-records` con el header `X-API-Key: test-api-key-123`.

### 1.4 Abrir Scalar (la UI de endpoints)
En el navegador: **`http://localhost:5050/scalar`**

Verás los endpoints agrupados:
- **Ingestion** → crudo en tiempo real (`GET /data-records`).
- **Series execution** → data procesada (`GET /series`, `GET /series/{id}/result`).

---

## 2. Guion de la demo (1 minuto)

### Paso 1 — Mostrar Scalar vacío
1. Abre `http://localhost:5050/scalar`.
2. Ejecuta **`GET /api/v1/movement-monitoring/data-records`** → responde `[]` (crudo vacío).
3. Ejecuta **`GET /api/v1/movement-monitoring/series`** → responde `[]` (procesado vacío).

> Frase: *"El edge ya está corriendo; por eso veo el contrato de endpoints. Pero todavía no entra data, así que ambos GET están vacíos."*

### Paso 2 — Abrir la serie
Para que el edge sepa qué meta evaluar y para vincular las lecturas, hay que **abrir una serie**.

- **Si tu firmware del Wokwi llama a `series/start` solo:** salta este paso.
- **Si no (caso típico):** ejecútalo a mano desde Scalar:

**`POST /api/v1/movement-monitoring/series/start`**
Header `X-API-Key: test-api-key-123`, body:
```json
{
  "device_id": "uflex-kit-001",
  "target_rom": 60,
  "target_reps": 4,
  "movement_type": "flexion",
  "body_part": "codo",
  "max_safe_angle": 130
}
```
Respuesta `201` con la serie en `status: OPEN` y un `serie_id` (autogenerado si no lo mandas).

### Paso 3 — Levantar el Wokwi
Compila/levanta el embebido desde VS Code (extensión Wokwi). El kit empieza a mandar ángulos al edge. Cada POST se guarda en `movement_records` con el `serie_id` de la serie abierta.

> Espera ~10–15 s para acumular lecturas (idealmente 2–4 flexiones completas).

### Paso 4 — Cerrar la serie (procesar)
- **Si tu firmware llama a `series/end` solo:** salta este paso.
- **Si no:** ejecútalo a mano:

**`POST /api/v1/movement-monitoring/series/end`**
Header `X-API-Key: test-api-key-123`, body:
```json
{ "device_id": "uflex-kit-001" }
```
El edge clasifica cada repetición (buena / incompleta / insegura), agrega el resultado y lo guarda en `serie_executions` como `status: CLOSED`.

### Paso 5 — Volver a mostrar los GET (ahora con data)
1. **`GET /data-records`** → ahora devuelve el array de ángulos crudos, cada uno con su `serie_id`.
2. **`GET /series`** → ahora devuelve la fila procesada: `reps_done`, `good_reps`, `bad_reps_incomplete`, `bad_reps_unsafe`, `avg_rom`, `valoracion`, `dangerous_movement_detected`.

> Frase de cierre: *"El edge recibió los datos crudos en tiempo real, los guardó, los procesó, y generó este resultado clínico. Esto último —el procesado— es lo que el edge enviaría al backend y lo que consumirían el móvil y la web."*

---

## 3. Endpoints de referencia

| Método | Ruta | Para qué |
|--------|------|----------|
| `GET` | `/scalar` | UI de documentación (lo que proyectas) |
| `GET` | `/status` | Salud del edge |
| `POST` | `/api/v1/movement-monitoring/series/start` | Abrir serie (define metas, devuelve `serie_id`) |
| `POST` | `/api/v1/movement-monitoring/data-records` | Ingesta de una lectura cruda (lo que hace el Wokwi) |
| `GET` | `/api/v1/movement-monitoring/data-records` | **Ver crudo** (real time) |
| `POST` | `/api/v1/movement-monitoring/series/end` | Cerrar serie y **procesar** |
| `GET` | `/api/v1/movement-monitoring/series` | **Ver procesado** (historial) |
| `GET` | `/api/v1/movement-monitoring/series/{id}/result` | Ver un resultado procesado puntual |

Credenciales del kit de prueba: `device_id=uflex-kit-001`, `X-API-Key=test-api-key-123`.

---

## 4. Notas para que no falle en vivo

- **El procesado solo aparece tras `series/end`.** Si solo POSteas lecturas sin abrir/cerrar serie, `GET /series` seguirá vacío (aunque `GET /data-records` sí muestre el crudo).
- **Las lecturas se vinculan a la serie abierta.** Si llegan lecturas sin ninguna serie `OPEN`, se guardan con `serie_id = null` y no entran en el resumen. Abre la serie **antes** de levantar el Wokwi.
- **Para repetir la demo:** borra `uflex_edge.db` y reinicia el edge, o simplemente abre una serie nueva (el `serie_id` será distinto y el historial se va acumulando).
- **Mismo `serie_id` en ambas tablas:** puedes filtrar `movement_records` y `serie_executions` por el `serie_id` para evidenciar el vínculo crudo→procesado.
