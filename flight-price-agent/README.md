# Agente de precios de vuelos ✈️

Revisa **todos los días** los precios de vuelos entre un conjunto de aeropuertos
definidos, busca el precio más barato para **cada fecha de salida** dentro de una
ventana (por ejemplo, de acá a 60 días) y te manda un **reporte por mail** con:

- Un resumen por ruta: precio mínimo, fecha y variación contra el día anterior.
- Alertas 🔔 cuando hay fechas por debajo del umbral de precio que definas.
- Una marca de **mínimo histórico** cuando el precio es el más bajo registrado.
- Las N fechas más baratas de cada ruta, con aerolínea, escalas y link.
- Un calendario con colores (verde = barato, rojo = caro) con el precio de cada día.

Usa sólo la librería estándar de Python (3.11 o más nueva), sin dependencias.

## Uso rápido

```bash
cd flight-price-agent
cp config.example.toml config.toml   # editá aeropuertos, fechas y umbrales

# Probar sin API ni mail (precios ficticios, guarda report.html)
python -m price_agent --provider demo --dry-run

# Corrida real con envío de mail
export TRAVELPAYOUTS_TOKEN=...        # o SERPAPI_KEY si usás serpapi
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587
export SMTP_USER=tu_cuenta@gmail.com SMTP_PASSWORD=tu_app_password
export MAIL_TO=tu_cuenta@gmail.com    # varios destinatarios separados por coma
python -m price_agent
```

## Configuración (`config.toml`)

| Sección | Clave | Descripción |
|---|---|---|
| `search` | `provider` | `travelpayouts`, `serpapi` o `demo` |
| | `currency` | Moneda (`USD`, `ARS`, `EUR`…) |
| | `days_ahead_start` / `days_ahead_end` | Ventana de fechas de salida, en días desde hoy |
| | `stay_nights` | Opcional: busca ida y vuelta con esa cantidad de noches |
| | `direct_only` | Sólo vuelos directos |
| `airports` | `origins` / `destinations` | Códigos IATA; se revisan todas las combinaciones |
| `alerts` | `DEST = precio` o `"ORIG-DEST" = precio` | Umbral para resaltar fechas baratas |
| `report` | `top_n`, `change_threshold_pct` | Fechas a listar y % de variación a destacar |
| `storage` | `history_db` | Archivo SQLite con el histórico |

## Proveedores de precios

| Proveedor | Costo | Datos | Requests por corrida |
|---|---|---|---|
| **Travelpayouts** (Aviasales) | Gratis, [token acá](https://www.travelpayouts.com/) | Cacheados (búsquedas de las últimas 48 h); puede haber días sin precio | 1 por ruta y mes |
| **SerpApi** (Google Flights) | Plan gratis limitado, después pago, [key acá](https://serpapi.com/) | Tiempo real | 1 por ruta y **día** (6 rutas × 54 días = 324) |
| **Demo** | – | Ficticios | 0 |

Con SerpApi conviene acotar la ventana de fechas o la cantidad de rutas para no
agotar la cuota.

## Ejecución diaria automática (GitHub Actions)

El workflow `.github/workflows/flight-price-agent.yml` corre todos los días a las
08:00 (hora de Argentina) y guarda el histórico entre corridas con el cache de Actions.

1. Cargá estos *secrets* en **Settings → Secrets and variables → Actions**:
   - `TRAVELPAYOUTS_TOKEN` (o `SERPAPI_KEY`)
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_TO` y opcionalmente `MAIL_FROM`
2. Creá y commiteá `flight-price-agent/config.toml` con tus aeropuertos. Si no existe,
   se usa `config.example.toml`.
3. Los cron de GitHub sólo corren en la **rama por defecto**: mergeá esta rama a `master`.
4. Para probar a mano: **Actions → Flight price agent → Run workflow**. Con `dry_run`
   no manda mail y deja el reporte como artefacto descargable.

Para cambiar el horario, editá la línea `cron` (está en UTC).

### Gmail

Con Gmail tenés que usar una [contraseña de aplicación](https://myaccount.google.com/apppasswords)
(requiere verificación en dos pasos), no tu contraseña normal:
`SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`.

## Tests

```bash
cd flight-price-agent
python -m unittest discover -s tests -t . -v
```
