# Agente de precios de vuelos ✈️

Revisa **dos veces por día** (00:00 y 10:00, hora de Argentina) los precios de vuelos entre un conjunto de aeropuertos
definidos, busca el precio más barato para **cada fecha de salida** (una ventana de
días o fechas puntuales, sólo ida o ida y vuelta con un rango de noches) y te manda
un **reporte por mail** y un **resumen por WhatsApp** con:

- El ranking de los viajes más baratos entre todas las rutas.
- El mejor precio por destino.
- Un resumen por ruta: precio mínimo, fechas y variación contra la corrida anterior.
- Alertas 🔔 cuando hay fechas por debajo del umbral de precio que definas.
- Una marca de **mínimo histórico** cuando el precio es el más bajo registrado.
- Las N fechas más baratas de cada ruta, con aerolínea, escalas y link.
- Una tabla con colores (verde = barato, rojo = caro): fecha de ida × noches de
  estadía, o un calendario con el precio de cada día si la ventana es larga.

La configuración actual (`config.toml`) busca **Argentina → playas de Brasil**:
salida el 2, 3 o 4 de enero de 2027 y vuelta entre 12 y 14 noches después, desde
EZE, AEP, COR, ROS y MDZ hacia 15 aeropuertos de playa (Florianópolis, Camboriú,
Río, Búzios, Salvador, Maceió, Recife, Natal, Fortaleza, Jericoacoara, etc.).

Usa sólo la librería estándar de Python (3.11 o más nueva), sin dependencias.

## Uso rápido

```bash
cd flight-price-agent
cp config.example.toml config.toml   # editá aeropuertos, fechas y umbrales

# Probar sin API ni mail (precios ficticios, guarda report.html)
python -m price_agent --provider demo --dry-run

# Corrida real con envío de mail y/o WhatsApp
export TRAVELPAYOUTS_TOKEN=...        # o SERPAPI_KEY si usás serpapi
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587
export SMTP_USER=tu_cuenta@gmail.com SMTP_PASSWORD=tu_app_password
export MAIL_TO=tu_cuenta@gmail.com    # varios destinatarios separados por coma
export WHATSAPP_PHONE=+5491112345678 CALLMEBOT_APIKEY=...   # opcional
python -m price_agent
```

## Configuración (`config.toml`)

| Sección | Clave | Descripción |
|---|---|---|
| `search` | `provider` | `travelpayouts`, `serpapi` o `demo` |
| | `currency` | Moneda (`USD`, `ARS`, `EUR`…) |
| | `days_ahead_start` / `days_ahead_end` | Ventana de fechas de salida, en días desde hoy |
| | `departure_dates` | Fechas de salida puntuales (`["2027-01-02", ...]`); reemplazan a la ventana |
| | `stay_nights_min` / `stay_nights_max` | Ida y vuelta: rango de noches (o `stay_nights` para un valor fijo) |
| | `direct_only` | Sólo vuelos directos |
| `airports` | `origins` / `destinations` | Códigos IATA; se revisan todas las combinaciones |
| `alerts` | `DEST = precio` o `"ORIG-DEST" = precio` | Umbral para resaltar fechas baratas |
| `report` | `top_n`, `top_overall`, `max_routes_detail`, `change_threshold_pct` | Viajes por ruta, tamaño del ranking general, rutas con detalle y % de variación a destacar |
| `storage` | `history_db` | Archivo SQLite con el histórico |

## Proveedores de precios

| Proveedor | Costo | Datos | Requests por corrida |
|---|---|---|---|
| **Travelpayouts** (Aviasales) | Gratis, [token acá](https://www.travelpayouts.com/) | Cacheados (búsquedas de las últimas 48 h); puede haber días sin precio | 1 por ruta y mes |
| **SerpApi** (Google Flights) | Plan gratis limitado, después pago, [key acá](https://serpapi.com/) | Tiempo real | 1 por ruta, fecha y estadía (75 rutas × 3 fechas × 3 estadías = 675) |
| **Demo** | – | Ficticios | 0 |

Con SerpApi conviene acotar orígenes, destinos o fechas para no agotar la cuota.
Travelpayouts es ideal para una búsqueda amplia como la actual, pero como sus precios
salen de búsquedas recientes de otros usuarios, algunas rutas poco buscadas pueden
aparecer "sin precio".

## Ejecución diaria automática (GitHub Actions)

El workflow `.github/workflows/flight-price-agent.yml` corre todos los días a las
**00:00 y 10:00** (hora de Argentina) y guarda el histórico entre corridas con el cache
de Actions. Cada corrida se compara con la anterior.

1. Cargá estos *secrets* en **Settings → Secrets and variables → Actions**:
   - `TRAVELPAYOUTS_TOKEN` (o `SERPAPI_KEY`)
   - Mail: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_TO` y opcionalmente `MAIL_FROM`
   - WhatsApp (opcional, ver abajo): `WHATSAPP_PHONE` y `CALLMEBOT_APIKEY`
2. Creá y commiteá `flight-price-agent/config.toml` con tus aeropuertos. Si no existe,
   se usa `config.example.toml`.
3. Los cron de GitHub sólo corren en la **rama por defecto**: mergeá esta rama a `master`.
4. Para probar a mano: **Actions → Flight price agent → Run workflow**. Con `dry_run`
   no manda mail y deja el reporte como artefacto descargable.

Para cambiar el horario, editá las líneas `cron` (están en UTC: Argentina = UTC−3).

## WhatsApp

El resumen (los 5 viajes más baratos y las alertas) se manda por WhatsApp si está
definido `WHATSAPP_PHONE`. Mail y WhatsApp son independientes: podés usar uno o ambos.

### Opción gratuita: CallMeBot (recomendada para uso personal)

1. Agendá el número de CallMeBot en tu teléfono. El número vigente está en
   https://www.callmebot.com/blog/free-api-whatsapp-messages/ porque a veces cambia.
2. Desde tu WhatsApp mandale el mensaje: `I allow callmebot to send me messages`
3. Te responde con tu **API key**.
4. Cargá los secrets:
   - `WHATSAPP_PHONE`: tu número en formato internacional **con el 9** de celulares
     argentinos, por ejemplo `+5491112345678`.
   - `CALLMEBOT_APIKEY`: la key que te llegó.

CallMeBot sólo puede mandar mensajes al número que lo activó.

### Opción paga: Twilio

Cargá `WHATSAPP_PROVIDER=twilio`, `WHATSAPP_PHONE`, `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN` y `TWILIO_WHATSAPP_FROM` (el número de WhatsApp de Twilio o el del sandbox).

### Gmail

Con Gmail tenés que usar una [contraseña de aplicación](https://myaccount.google.com/apppasswords)
(requiere verificación en dos pasos), no tu contraseña normal:
`SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`.

## Tests

```bash
cd flight-price-agent
python -m unittest discover -s tests -t . -v
```
