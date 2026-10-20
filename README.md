# Solar VPS · VM II Premium+ 12K

Primera versión para un inversor, alojada en tu propio Ubuntu. Recolector independiente de la web, PostgreSQL persistente, panel con gráficos y exportaciones Excel/CSV/JSONL. Sin comandos de control al inversor.

## Esquema de energía y meteorología de Valdivia

El panel incluye ilustraciones SVG de paneles, inversor, batería, red y casa. Las partículas animadas indican las entradas y salidas reportadas. La batería cambia de dirección entre carga y descarga y su indicador refleja el SOC. Se pausa la animación si la lectura tiene más de diez minutos, falta la hora interpretable o hay carga y descarga simultáneas. La potencia negativa de red no se interpreta automáticamente como exportación, porque ese convenio no se ha confirmado para el equipo. Se respeta la preferencia del sistema de reducir movimiento.

El servicio Docker `weather` descarga Open-Meteo cada 15 minutos, sin usar la cuenta del inversor y aunque la web esté cerrada. Para iniciarlo en Ubuntu: `docker compose up -d --build weather`. La prueba local lo inicia en un hilo independiente al abrir `local_preview.py`.

La referencia geográfica es el centro de Valdivia, Los Ríos (-39.81422, -73.24589). Se pueden ajustar `WEATHER_LATITUDE` y `WEATHER_LONGITUDE` en `.env`. La fuente es un **modelo meteorológico horario**, no una estación junto a los paneles ni radiación medida por el inversor. La radiación global horizontal GHI, directa y difusa está en W/m² y promedia la hora anterior. No equivale a la irradiancia sobre paneles inclinados. Se conserva temperatura, humedad, precipitación total, lluvia, chubascos, código de tiempo, nubosidad, viento, presión, GHI, radiación directa/difusa y DNI, con unidades y metadatos.

Se guarda la respuesta completa en `captures` con `source=weather` y las series horarias en `measurements` con esa misma fuente. Los objetos tienen `data_kind=weather_model_hourly`, coordenadas, unidades, fecha válida UTC y fecha de descarga; las revisiones del modelo se conservan. Las horas futuras de la respuesta solo permanecen en el JSON original y no se insertan como condiciones históricas en la serie normalizada. La consulta recupera al menos tres días recientes y hasta 92 días para cubrir desconexiones; huecos más antiguos requieren otra fuente histórica. El archivo no se elimina automáticamente.

El gráfico permite seleccionar radiación, temperatura, nubosidad, precipitación, chubascos, lluvia, viento, humedad y presión de Valdivia. La exportación global incluye la meteorología, identificada por `source=weather` y un identificador de ubicación. El enlace del clima descarga solo esas filas. Las fechas UTC permiten cruzarlas con las lecturas del inversor; GHI de las 15:00 es el promedio de 14:00 a 15:00 y debe compararse con la energía/potencia de ese intervalo. Se conservan originales y revisiones para análisis posteriores.

Fuente y atribución: [Open-Meteo, CC BY 4.0](https://open-meteo.com/). [Definiciones y documentación](https://open-meteo.com/en/docs). Su API gratuita está prevista para uso personal/no comercial; este uso doméstico no requiere clave. Para uso comercial debe configurarse una cuenta/servicio apropiado según sus condiciones.

## Estado de validación

El conector deriva de las llamadas y la firma encontradas en el [JavaScript público del portal](https://tumcapp.com/static/js/app.76b3ac37cac31f9f64db.js) el 20 de octubre de 2026. Se obtuvo una lectura actual real con la cuenta del propietario. La descarga histórica completa aún debe verificarse con el proveedor. No es una API pública documentada. No se ha instalado en tu VPS: no se ha proporcionado acceso. Se probaron sincronización, checkpoints, almacenamiento y exportaciones con respuestas simuladas y PGlite local. Consulta `PRUEBA-LOCAL.md`. Docker/PostgreSQL 17 deben verificarse en Ubuntu siguiendo los pasos siguientes.

No se usa el iPhone ni se automatiza la app. El portal se aloja en `tumcapp.com`, pero su configuración pública declara la API en `https://isolar.tumcapp.com`. El conector consulta esa API. Sí se sigue usando la nube a la que consulta el portal i.Solar. No se ha identificado otro servicio del fabricante independiente de esa nube. Si esta cae, no habrá lecturas nuevas; las ya guardadas siguen en tu VPS.

## Instalación en Ubuntu

Requisitos: Docker Engine con el plugin Docker Compose, puerto SSH disponible y espacio para PostgreSQL. Copia esta carpeta al VPS, por ejemplo a `/opt/solar-vps`, y trabaja dentro de ella.

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Completa los valores vacíos:

- `POSTGRES_PASSWORD`: contraseña nueva y larga para la base local.
- `DASHBOARD_USER` / `DASHBOARD_PASSWORD`: acceso al panel; usa una contraseña distinta.
- `SOLAR_USERNAME` / `SOLAR_PASSWORD`: cuenta existente del portal tumcapp.com; no las envíes por chat. En valores con `$`, `#`, espacios o comillas, utiliza las reglas de comillas de archivos `.env` de Docker Compose. Comillas simples evitan interpolar `$`.
- `SOLAR_DEVICE_SN`: número de serie del equipo que aparece en el portal.
- `DEVICE_TIMEZONE`: zona de las fechas que entrega el proveedor. Inicialmente `America/Santiago`; confirma que la hora del equipo coincide. Siempre se guarda también la fecha original sin modificar.
- `HISTORY_START_DATE=2026-10-18`: fecha de instalación indicada por el propietario.
- `HISTORY_SYNC_SECONDS=300`: valor inicial de 5 minutos. Se admiten 60, 300, 600 y 900 segundos (1, 5, 10 y 15 minutos). El panel permite cambiarlo sin reiniciar: el valor elegido se guarda en PostgreSQL y prevalece sobre el valor inicial del archivo. Es una elección de la app, no un límite documentado del proveedor. Incluye todas las muestras disponibles dentro del periodo; no una sola muestra por consulta. No se encontró una cuota pública de solicitudes.

Primero inicia la base y la web, y valida una sincronización histórica completa:

```bash
docker compose up -d --build db web
docker compose run --rm collector python collector.py --once
```

Si sale `Historial sincronizado`, activa el recolector permanente:

```bash
docker compose up -d collector
docker compose logs --tail=30 collector
```

Ante un error, el proceso informa solo el tipo de error/código, sin volcar tokens ni respuestas de autenticación. Un rechazo de firma o login requiere ajustar el conector antes de continuar. No compartas `.env` ni salidas que contengan credenciales.

## Abrir el panel

Por defecto solo se expone en `127.0.0.1:8088` del VPS. Desde tu ordenador:

```bash
ssh -L 8088:127.0.0.1:8088 usuario@IP_DEL_VPS
```

Abre http://localhost:8088 e introduce las credenciales `DASHBOARD_*`. Para usar un dominio, configura tu proxy inverso con HTTPS hacia `127.0.0.1:8088`. El acceso básico debe viajar por el túnel SSH o por HTTPS. PostgreSQL no publica puertos.

El gráfico tiene rangos rápidos (1 h, 6 h, 24 h, hoy, ayer, 7 días y todo), navegación al periodo anterior/siguiente, acercar/alejar y ajuste a los datos disponibles. También puedes arrastrar horizontalmente para ampliar un intervalo; doble clic vuelve al periodo anterior. El eje X adapta las etiquetas entre horas y fechas según la amplitud del periodo. Las fechas manuales siguen disponibles.

La sección **Exportar todos los datos**, encima del gráfico, descarga todas las mediciones y todos sus campos en CSV o todas las respuestas originales en JSONL. No aplica filtros de fecha, variable ni el límite del gráfico. Incluye campos nuevos y anidados; los objetos anidados se escriben como JSON en la celda CSV. Las exportaciones por rango siguen disponibles junto a las fechas.

Las rutas API devuelven errores JSON, también cuando falla la base o expira una sesión. La web comprueba la respuesta y muestra un mensaje legible si recibe HTML de un proxy, pierde conexión o agota el tiempo de espera. La lectura bajo demanda muestra su estado sin borrar el historial guardado.

## Qué se guarda

- `captures`: cada respuesta exitosa completa de lecturas o páginas históricas, parámetros de la consulta y hora de recepción UTC. No incluye respuestas del login, tokens ni contraseña.
- `measurements`: cada objeto de medición completo en JSONB, separado para consultas; deduplica objetos idénticos dentro de cada fuente. Capturas repetidas permanecen en `captures` para auditar frescura y disponibilidad.
- `events`: éxito o fallo de cada intento de recolección.

No se borran registros automáticamente y no se reemplazan originales por promedios. Los campos nuevos también se conservan. No se inventan ceros para variables ausentes. La pantalla muestra métricas habituales del portal; el JSON conserva el resto. Esta versión no recolecta por separado los endpoints de alarmas ni configuración: guarda lo que devuelven lecturas e historial.

El gráfico incluye el historial descargado y usa la fecha de medición, con la fecha de recepción como respaldo si el campo del proveedor no es interpretable. Máximo 5000 objetos por consulta; usa periodos menores para explorar. CSV y JSONL transmiten todos los registros del rango sin ese límite. El CSV filtra por fecha de medición y usa formato largo (una fila por campo); protege cadenas que podrían ejecutarse como fórmulas en Excel. El JSONL filtra por **fecha de recepción** y conserva las respuestas originales. No se calculan kWh integrando potencias todavía.

## Funcionamiento automático

El proceso `collector` descarga primero el historial desde el 18 de octubre de 2026. Consulta en lotes de hasta 31 días y recorre todas las páginas. Guarda un checkpoint solo cuando termina el lote. Repite la sincronización según el intervalo elegido, volviendo a consultar dos días anteriores para recoger datos tardíos. Tras una desconexión continúa desde el avance guardado, con ese solapamiento. Los fallos tienen espera creciente, hasta cuatro horas. Las páginas se espacian un segundo. Ante HTTP 429 se espera al menos cinco minutos y se respeta `Retry-After` si es mayor. La semántica del final de rango se cubre con un día adicional de solapamiento y debe contrastarse con el portal real.

La prueba local se prepara a un minuto para evaluar rápidamente. El panel muestra duración, páginas y registros nuevos del último ciclo. Nunca se solapan ciclos: si una descarga tarda más que el intervalo, se termina primero y se espera al menos cinco segundos. Cambiar de 1 a 5 o 10 minutos desde el panel no requiere volver a introducir credenciales. Estos intervalos se probaron con reloj simulado y con persistencia real de la configuración; no equivalen a una validación de la cuota de la API. En 100 muestras históricas recibidas, la separación mediana observada fue de 300 segundos; el ritmo puede variar.

No hay consultas actuales periódicas con la web cerrada. Al abrir el panel, este solicita una lectura actual y la renueva como máximo una vez por minuto mientras está visible; el botón permite pedirla manualmente respetando ese límite. Las lecturas se guardan también. Cerrar el panel no detiene la sincronización histórica. Para una lectura actual desde consola:

```bash
docker compose run --rm collector python collector.py --realtime-once
```

## Importar historia disponible en el proveedor

La sincronización automática cubre el rango configurado. También se puede importar manualmente un rango adicional:

```bash
docker compose run --rm collector python collector.py --history 2026-10-19 2026-10-20
```

Usa el endpoint de tablas históricas y recorre `data.list` con paginación. Si cambia el formato, repite páginas o deja páginas pendientes, se detiene sin marcar completo ese lote. Repetir una importación conserva nuevas capturas y evita duplicar mediciones idénticas. La fecha y resolución originales dependen del proveedor. No se puede recuperar detalle que ya haya eliminado o nunca registrado. Una interrupción que dure más que la retención de su nube puede dejar huecos irrecuperables.

## Respaldo y mantenimiento

El volumen `solar_data` sobrevive a recreaciones de contenedores. No ejecutes `docker compose down -v`: elimina el volumen.

```bash
mkdir -p backups
chmod 700 backups
docker compose exec -T db pg_dump -U solar solar | gzip > backups/solar.sql.gz
chmod 600 backups/solar.sql.gz
```

Guarda una copia fuera del VPS. El comando sobrescribe el archivo anterior: asigna nombres diferentes para conservar varias fechas. Respalda `.env` de forma segura por separado. Prueba la restauración en una base vacía antes de depender del respaldo. Los datos crecen sin límite de retención; vigila disco y respaldos. Configura tu propia programación de respaldos en Ubuntu.

## Desarrollo y pruebas

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
node --test tests/frontend.test.cjs
```

Las rutas de lectura permitidas en `cloud.py` son exclusivamente:

```text
POST /api/admin/user/login
POST /api/admin/realData/getRealByDeviceSn
POST /api/admin/workInfo/getHistoricalData
```

El portal usa contraseña MD5 en su protocolo de login (excepto usuarios VCN), token y firma `vrt` SHA-256 sobre parámetros. Se reproduce por compatibilidad, siempre sobre HTTPS con validación TLS. No se proporciona garantía de estabilidad del proveedor. Mantén las dependencias y las imágenes actualizadas.


## Excel y consultas meteorológicas SQL

El botón **Excel completo + gráficos** consulta exclusivamente PostgreSQL: todas las fechas y variables, sin los filtros ni el límite de 5000 filas del gráfico web. Incluye seis gráficos meteorológicos, la última revisión de cada hora en `Clima`, y todas las mediciones/revisiones de ambas fuentes en `Datos`. Los campos largos se dividen en partes y se crean más hojas si se alcanza el límite de filas de Excel. Las respuestas originales completas siguen disponibles en JSONL. Las fechas se presentan en UTC. Los gráficos de Excel muestrean uniformemente periodos que superen 30.000 horas; las hojas conservan todos los datos.

El contenedor Python usa XlsxWriter para generar descargas en el servidor, con archivos temporales y memoria constante; no requiere Excel instalado ni el runtime de Codex. Reconstruir `web` al actualizar dependencias: `docker compose up -d --build web weather`.

Las variables climáticas se guardan en PostgreSQL como números JSONB consultables con SQL. La respuesta original y unidades permanecen en `captures.response`; cada hora y sus unidades en `measurements.payload`. No dependen de exportar Excel ni de visitar la página. Ejemplo con la última revisión de cada hora (todas las revisiones se conservan):

```sql
SELECT DISTINCT ON (device_sn, observed_at)
  observed_at AS fecha_utc, received_at AS descargado_utc, device_sn,
  (payload->>'temperature_2m')::double precision AS temperatura_c,
  (payload->>'showers')::double precision AS chubascos_mm,
  (payload->>'cloud_cover')::double precision AS nubosidad_pct,
  (payload->>'precipitation')::double precision AS precipitacion_mm,
  (payload->>'wind_speed_10m')::double precision AS viento_kmh,
  (payload->>'shortwave_radiation')::double precision AS irradiancia_w_m2,
  payload->'units' AS unidades
FROM measurements
WHERE source='weather' AND observed_at <= now()
ORDER BY device_sn, observed_at, id DESC;
```

Los chubascos forman parte de la precipitación total: no se deben sumar ambos campos. Los valores que el proveedor no entregue permanecen nulos, sin sustituirlos por cero. Fuente: https://open-meteo.com/en/docs.
