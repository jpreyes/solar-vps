# Resultado de la prueba local

Se levantó la aplicación en Windows, en `http://127.0.0.1:8088`, con una base Postgres embebida PGlite que escucha solo en `127.0.0.1:55432`. Esto prueba consultas PostgreSQL reales, pero no sustituye la validación de Docker y PostgreSQL 17 en Ubuntu.

## Comprobado

- Veintitrés pruebas Python del conector, autenticación, sincronización histórica, intervalos de 1/5/10 minutos, prevención de solapamientos, límites HTTP 429 y respuestas JSON de error; ocho pruebas JavaScript de respuestas API, sesión, conexión y controles temporales.
- Once comprobaciones de integración mediante HTTP y la base local: conservación de cada respuesta, deduplicación, campos anidados, historial, CSV, JSONL, protección de rutas, formulario de conexión, rechazo de otro origen y de credenciales vacías.
- Persistencia de JSONB después de cerrar y reabrir una base PGlite en disco.
- Panel y formulario abiertos y revisados en Chrome. El panel vacío muestra cero registros y campos ausentes como `—`.
- Se obtuvieron y conservaron lecturas actuales reales de la cuenta del propietario tras corregir la dirección de la API.
- Los datos sintéticos de las pruebas de integración se eliminaron únicamente por sus números de serie temporales. Las lecturas reales del usuario se conservaron.
- Se comprobó que la sincronización guarda el checkpoint, evita duplicar mediciones y no avanza el checkpoint tras un fallo. Gráficos y CSV incluyen mediciones por su fecha original, aunque se descarguen después.

## Prueba con el inversor

Abre `http://127.0.0.1:8088/local`. Aparece un formulario HTML de ingreso; no depende de ventanas de autenticación HTTP del navegador. Acceso del panel de prueba: usuario `admin`, contraseña `solar-local`. Estas son credenciales locales de prueba, distintas de las del proveedor. Se comprobó por separado el ingreso por formulario, la cookie de sesión y el rechazo de solicitudes de otro origen.

En el formulario introduce tu usuario y contraseña de tumcapp.com y el número de serie del inversor. Se comprobará una lectura actual y comenzará la descarga histórica desde el 18 de octubre de 2026. La prueba local está preparada a 1 minuto y el panel permite cambiar a 5, 10 o 15 sin reiniciar ni volver a introducir la cuenta. Las lecturas actuales se pedirán solo cuando visites el panel o uses el botón de actualización. Las credenciales del proveedor quedan solo en memoria. El cierre del proceso corta la conexión. En el VPS, el contenedor `collector` funciona independientemente de que visites el panel.

Se validaron los intervalos 60/300/600 segundos con reloj simulado, persistencia real en la base y la API local de configuración. Aún no se ejecutó una comparación temporizada real contra la nube con estos tres intervalos: falta reconectar la cuenta en la sesión local actual. No se encontró una cuota pública para esta API. En las 100 muestras históricas descargadas se observó una separación mediana de 300 segundos y mínima de 17 segundos; esto no garantiza un ritmo fijo. La interfaz muestra duración, páginas y registros nuevos para valorar si consultar a un minuto aporta datos antes que a cinco.

La API correcta es `https://isolar.tumcapp.com`. Se validaron el acceso y las lecturas actuales reales, y se recibieron registros históricos. Falta verificar la descarga histórica completa desde el día 18 y su resolución. Las sesiones locales deben reiniciarse tras un reinicio del ordenador o del proceso.

Se detectó que PGlite, utilizado solo en esta prueba local, admite un backend y rechazaba conexiones simultáneas. Se añadió acceso serializado durante cada transacción y se evitó mantener la base ocupada durante consultas al proveedor. Esta opción se activa exclusivamente en `local_preview.py`; Ubuntu sigue utilizando PostgreSQL normal. Se hizo una copia de seguridad de la base antes de reiniciarla. Pasaron 48 operaciones concurrentes de lectura/escritura y 24 solicitudes HTTP concurrentes al servidor activo, sin respuestas HTML ni errores de conexión a la base. Los rechazos 409 en la prueba HTTP indican que falta reconectar la cuenta; las respuestas 202 indican otra consulta en curso.

Se añadieron rangos rápidos, navegación temporal, zoom, selección por arrastre y eje X adaptativo. Se verificaron la sintaxis JavaScript y la lógica temporal mediante pruebas; la versión final no se verificó visualmente en el navegador integrado por una restricción de acceso de ese navegador.

La exportación global CSV/JSONL ignora filtros de fecha y variable y no limita el número de registros. Se comprobó con datos temporales de fechas 1901 y 2099, varias variables y un campo anidado. Los datos temporales se retiraron. Se comprobó autenticación y la disponibilidad de la base antes de comenzar el archivo.

Para el backend embebido también se desactivó la preparación automática de sentencias de psycopg, que no es adecuada para esta conexión de prueba con un único backend compartido. Pasó una importación de 300 filas en tres páginas de 100 con conexiones nuevas, seguida de ambas exportaciones. PostgreSQL del VPS mantiene su configuración normal. Se guardó una copia de seguridad adicional antes de reiniciar PGlite.

## Rediseño y archivo meteorológico

Se añadió un esquema SVG con ilustraciones de paneles, inversor, batería, red y casa, partículas animadas y resumen del estado. La lógica se comprobó con carga, descarga, datos ausentes, lecturas antiguas y sentidos contradictorios. Las animaciones respetan la reducción de movimiento. Se mantienen los filtros, gráficos, lectura bajo demanda y exportaciones globales.

La ubicación de Valdivia se verificó con el geocodificador de Open-Meteo: Los Ríos, -39.81422/-73.24589. Se recuperaron y guardaron 92 horas de meteorología real del proveedor (estimaciones horarias de modelos), incluyendo GHI y radiación directa/difusa en W/m², temperatura, nubes, precipitación, viento, humedad, presión y DNI. Se conservó el JSON completo con sus unidades y la serie normalizada excluyó horas futuras. Las revisiones se conservan. Los datos meteorológicos no se presentan como mediciones de una estación en la instalación.

El proceso meteorológico de prueba local arranca sin iniciar sesión en el proveedor del inversor. El paquete Ubuntu incluye el servicio Docker `weather`, que funciona con la web cerrada. Se añadieron tres pruebas Python para importación horaria, unidades, valores nulos, formato incompleto y exclusión de horas futuras, y dos pruebas JavaScript para sentidos y antigüedad de flujos. Total: 26 pruebas Python y 10 JavaScript. La verificación visual del navegador integrado sigue pendiente por la restricción de acceso previamente indicada.
