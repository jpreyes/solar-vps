# Análisis con datos reales · octubre 2026

Datos usados: historial de 5 min del inversor del 17 al 20 de octubre, lecturas en tiempo real del 20 al 21 de octubre y meteorología horaria de Open-Meteo. También ~12 años (2015–oct 2026) de radiación horaria de Valdivia sobre el plano real de cada string, ambos orientados al **este**: **PV1 a 25°** y **PV2 a 40°**, 8 × 620 W cada uno (Open-Meteo archive, reanálisis ERA5). Con solo 4 días medidos, los valores del sistema se refinarán solos a medida que el VPS acumule datos. El panel recalcula todo cada hora.

## Lo que muestran tus datos

| Hallazgo | Evidencia | Consecuencia |
|---|---|---|
| Configuración actual ≈ **22/50** | Pasa a red con SOC 19–23 %; volvió a batería recién al 50 % (20-oct 10:37) | La casa queda en red por la mañana aunque haya sol |
| En modo red (L) **la casa consume de la red y el sol solo carga la batería** | 20-oct 09:00: solar 1.984 W → batería 1.945 W; carga 179 W desde la red | El umbral de retorno (el “50”) sí cuesta energía |
| `gridPowerInputActiveTotal` **no es importación en modo batería** | En modo B copia el consumo (1.333 W vs 1.376 W) con `statusGrid=0` | El panel antiguo decía “la red aporta” cuando no era así (corregido) |
| No carga la batería desde la red | Noches en modo L con SOC estable 19→18 % | Correcto con tarifa plana: cargar desde la red solo pierde ~20 % |
| Batería **15,36 kWh** según la placa (NM51.2-300ES01, LiFePO4 51,2 V × 300 Ah), pero el SOC varía como si fueran ~10,5–14 kWh | Energía integrada de carga y descarga vs cambio de SOC | El SOC del BMS probablemente aún no está calibrado (batería nueva) o el sensor de corriente del inversor mide bajo. Se aclara tras una carga completa y unas semanas de datos; el panel lo vigila |
| Consumo propio del inversor ≈ **50 W** | Descarga de batería − consumo, de noche | ≈ 1,2 kWh/día |
| Consumo de la casa ≈ **11–15 kWh/día** | Días completos 18–20 oct | Base nocturna 100–250 W y picos de 2–4 kW al atardecer |
| String PV1 sin tensión ~90 % del tiempo | `pvInputVoltage1` = 0 V con sol en PV2 | Falla puntual ya identificada; **el estudio supone PV1 y PV2 activos** (9,92 kWp) |
| BMS desconectado el 19-oct 10:50 | SOC 0 % y 31 V durante 2 lecturas, paso forzado a red | Probablemente durante la instalación de PV1; el panel ahora lo alerta |
| La hora del equipo es correcta | El solar arranca 07:00 y sigue la irradiancia horaria (UTC−3) | Se pueden cruzar con el clima sin corrección |
| **Se pierde sol a mediodía** | 18-oct: batería al 100 % a las 12:00 y el solar cae de 4 kW al consumo (~0,8 kW) | Sin exportación, el excedente se pierde |

Con tus dos strings al este (PV1 25°, PV2 40°; 9,92 kWp) y máximo de 8 kW, la radiación de Valdivia da en promedio **≈ 10.800 kWh/año**:

| Mes | Ene | Feb | Mar | Abr | May | Jun | Jul | Ago | Sep | Oct | Nov | Dic |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| kWh/día solar esperados | 51 | 44 | 33 | 21 | 14 | 10 | 12 | 17 | 26 | 36 | 43 | 50 |
| Día malo (percentil 10) | 36 | 26 | 16 | 8 | 5 | 3 | 3 | 5 | 11 | 17 | 23 | 30 |

La orientación este cuesta ~18 % de energía anual frente a una orientación norte, casi todo en invierno: en junio da ~10 kWh/día (orientada al norte serían ~17). En verano casi no se nota. El 43 % de la energía llega antes del mediodía, lo que favorece cargar la batería temprano. **De mayo a agosto la producción media queda por debajo de tu consumo (12–13 kWh/día)**: en esos meses la batería se llena con poca frecuencia.

## ¿20/30 en verano y 40/50 en invierno?

Simulación hora a hora, ~12 años de radiación, **PV1 25° este + PV2 40° este (9,92 kWp, tope 8 kW)**, **batería de 15,36 kWh**, tu consumo medido (11–13 kWh/día con +25 % en invierno) y el comportamiento real del modo red (la casa usa la red y el sol solo carga la batería). Eficiencias: carga 95 %, descarga + inversor 92 %, consumo propio 50 W. Costo: red a $230/kWh más desgaste a $45/kWh entregado (ajustable). “Días al 100 %” es el porcentaje de días de junio y julio en que la batería llega a carga completa. La racha es la típica anual de días seguidos sin llenarse (peor año entre paréntesis).

| Umbrales | Red kWh/año | Autosuficiencia | Días al 100 % jun–jul | Racha sin llenarse | Costo anual |
|---|---|---|---|---|---|
| 22/50 (actual) | 446 | 90,5 % | 23 % | 18 d (35) | $190.000 |
| 20/30 todo el año | **418** | **91,1 %** | 18 % | 20 d (42) | **$182.000** |
| 30/40 | 448 | 90,4 % | 25 % | 15 d (38) | $188.000 |
| 40/50 todo el año | 489 | 89,6 % | 31 % | 12 d (21) | $196.000 |
| 20/30 · 40/50 abr–sep | 483 | 89,7 % | 31 % | 12 d (21) | $195.000 |
| 20/30 · 40/50 may–ago | 465 | 90,1 % | 31 % | 12 d (21) | $191.000 |
| **20/30 · 40/50 jun–jul** | **438** | **90,7 %** | **31 %** | **12 d (21)** | **$186.000** |

Conclusiones:

1. **Tu intuición es correcta en lo técnico, aunque no por costo.** 20/30 todo el año es lo más barato. Pero con paneles al este el invierno es justo, y con 20/30 la batería puede pasar 20–40 días seguidos sin llenarse. Subir a 40/50 en invierno duplica la frecuencia de cargas completas y reduce a la mitad esas rachas. Eso importa para un LiFePO4: el BMS balancea las celdas y recalibra el SOC al llegar a 100 %.
2. **Recomendación: 20/30 de agosto a mayo y 40/50 en junio y julio.** Obtiene el mismo beneficio de cargas completas que aplicarlo de abril a septiembre, por solo ~20 kWh/año más de red (≈ $4.000). Además guarda ~3 kWh extra para cortes, unas 4–6 h de consumo normal, justo en la temporada de temporales.
3. **Bajar la vuelta a batería de 50 % a 30 % sigue siendo útil** (−28 kWh/año frente a tu 22/50 actual). En modo red la casa compra todo a la red aunque haya sol, y con paneles al este la mañana es tu mejor momento de producción.
4. Ir más bajo (15/25) no conviene: el ahorro es marginal, sube la profundidad de descarga y alarga aún más las rachas sin carga completa.
5. **Con temporal anunciado**, fuera de junio–julio, conviene subir temporalmente a 40/50. El panel avisa con ráfagas ≥ 70 km/h, y alerta si pasan 10 días sin carga completa.
6. **El sol perdido es enorme pero difícil de aprovechar**: ~6.200 kWh/año (≈ 58 % del potencial, casi todo de octubre a marzo), porque la batería se llena y no hay exportación. Con la batería de 15 kWh, mover consumo a la mañana ya solo ahorra ~30 kWh/año: la batería cubre casi todo. Ese excedente solo rinde exportándolo (net billing, Ley 20.571, con inversor/configuración que inyecte y declaración TE4) o con cargas nuevas en horas de sol que reemplacen gas o leña: termo eléctrico, bomba de calor o auto eléctrico.

## ¿Conviene girar PV1 al oeste?

Misma simulación (~12 años, batería de 15,36 kWh, consumo medido), cambiando solo PV1. PV2 queda a 40° este.

| Configuración | Solar kWh/año | Antes de 12 h / después de 15 h | Red kWh/año (20/30) | Ciclos de batería/año | Horas/año en modo red | Días al 100 % jun–jul* | Costo anual (20/30) |
|---|---|---|---|---|---|---|---|
| Actual: PV1 25° este | 10.764 | 43 % / 19 % | 417 | 124 | 931 | 31 % | $182.000 |
| PV1 40° oeste | 10.612 | 30 % / 35 % | 401 | 109 | 880 | 30 % | $168.000 |
| PV1 25° oeste | 10.925 | 31 % / 32 % | 388 | 111 | 854 | 31 % | $166.000 |

\* Con la estrategia 20/30 + 40/50 en junio–julio. La racha típica sin llenarse es de 12 días (peor 21) en la actual y en oeste 25°, y de 15 días (peor 28) en oeste 40°.

- **Oeste es algo mejor, pero poco.** La producción anual casi no cambia (−1 % a 40°, +1,5 % a 25°), y el invierno es igual: ~10 kWh/día en junio en los tres casos. Lo que cambia es el horario: con un string al oeste hay sol hasta las 19–20 h y cubre parte del peak de la tarde-noche sin pasar por la batería.
- **El ahorro de red es chico**: 16–29 kWh/año, unos $4.000–7.000. La diferencia de costo de la tabla viene sobre todo de **~12 % menos ciclos de batería** (124 → 109–111 al año), que alarga su vida útil en la misma proporción. Ese valor depende del desgaste supuesto ($45/kWh).
- **Si se gira, mejor a 25° que a 40°**: al oeste, 25° rinde ~300 kWh/año más y mantiene mejor las cargas completas de invierno.
- **Recomendación**: no justifica una obra solo por esto. Si la reparación de PV1 obliga a desmontar o recablear igual, y hay techo al oeste sin sombras, vale la pena dejarlo **al oeste a ~25°**. Si no, la configuración actual está bien.
- En la app basta con `PV1_AZIMUTH=270` (y `PV1_TILT`) en `.env` para que el pronóstico, el “solar esperado” y el estudio usen la nueva geometría.

## ¿Conviene cargar la batería también desde la red?

Configuración actual (PV1 25° este + PV2 40° este), batería de 15,36 kWh, tarifa plana. “Red→batería” es la energía de la red que entra a la batería. La vida útil es el tiempo hasta 80 % y 70 % de la capacidad original.

| Estrategia | Red kWh/año | Red→batería | Días al 100 % jun–jul | Racha sin llenarse (peor) | Vida a 80 % / 70 % | Costo anual* |
|---|---|---|---|---|---|---|
| 20/30 todo el año, solo solar | **418** | 0 | 18 % | 20 d (42) | 12,1 / 18,2 años | **$182.000** |
| 20/30 · 40/50 jun–jul, solo solar | 438 | 0 | 31 % | 12 d (21) | 12,0 / 18,0 años | $186.000 |
| **20/30 + carga de calibración desde la red** (una noche al 100 % tras 10 días sin llenarse) | 429 | 30 | 25 % | **9 d (10)** | 12,1 / 18,1 años | $185.000 |
| 20/30 + la red carga la batería siempre (“solar + red”, 3 kW) | 478 | 367 | 24 % | 19 d (27) | 11,7 / 17,5 años | $206.000 |
| 40/50 + la red carga siempre | 573 | 443 | 35 % | 10 d (21) | 11,4 / 17,2 años | ≈ $230.000 |
| Respaldo puro: 90/100 + red (batería siempre llena) | 2.185 | 1.409 | 100 % | 0 | 11,2 / 16,8 años | ≈ $570.000 |

\* Red a $230/kWh más desgaste de batería a $45/kWh entregado.

- **Cargar desde la red todo el tiempo es peor**: con tarifa plana se compra la misma energía y se pierde ~13 % al pasarla por la batería y el inversor. Son +60 kWh/año (≈ +$24.000) y más ciclos. Solo convendría con una tarifa horaria (noche barata), que no es la tarifa residencial BT1.
- **La carga de calibración sí conviene.** Cuesta ~11 kWh/año (≈ $3.000) frente a 20/30 puro, y deja la racha máxima sin carga completa en ~10 días, mejor que 40/50 en junio–julio (21 días) y más barata. Es un ajuste manual de 2 a 4 veces por invierno: cuando el panel avise “10 días sin llegar al 100 %”, poner el cargador en “solar + red” una noche y volver a “solo solar” al día siguiente.
- **Qué elegir:** si te importa la reserva ante cortes en invierno, 40/50 en junio–julio. Si prefieres lo más barato y saludable para el BMS, 20/30 todo el año con calibración desde la red cuando el panel lo pida. Las dos son buenas; la carga permanente desde la red, no.

## ¿Cuánto durará la batería?

Estimación aproximada para el LiFePO4 NM51.2-300ES01 con ~120 ciclos completos equivalentes al año:

- **≈ 12 años hasta 80 % de capacidad y ≈ 18 años hasta 70 %**, en cualquiera de las estrategias razonables. Las diferencias entre estrategias son de meses, no de años.
- Manda el **envejecimiento por calendario** (~1,25 %/año), no el uso (~0,4 %/año). 120 ciclos al año son pocos: 6.000 ciclos tardarían ~50 años.
- El factor que más pesa es la **temperatura del lugar** donde está la batería:

| Envejecimiento por calendario (25 °C, 50 % carga) | Batería a 15 °C | a 20 °C | a 25 °C |
|---|---|---|---|
| 1,0 %/año (optimista) | 20 / 30 años | 16 / 24 años | 12,5 / 19 años |
| 1,5 %/año (central) | 15 / 23 años | **12 / 18 años** | 9 / 14 años |
| 2,0 %/año (conservador) | 12,5 / 19 años | 9,6 / 14 años | 7 / 11 años |

  (años hasta 80 % / hasta 70 %). El modelo es lineal y por eso conservador: en la práctica el envejecimiento por calendario se frena con los años.
- Lo que más alarga la vida: mantenerla fresca (bajo techo, lejos del sol y de fuentes de calor; idealmente 15–20 °C), no tenerla al 100 % por largos periodos en verano y no cargar desde la red sin necesidad. La garantía típica de estos equipos es de 10 años o 6.000 ciclos; tu uso queda muy por debajo del límite de ciclos.
- Supuestos ajustables en `.env`: `BATTERY_TEMP_C`, `BATTERY_CALENDAR_PCT_YEAR`, `BATTERY_CYCLES_TO_80`. El panel muestra la vida estimada de cada estrategia.

## Ajustes sugeridos en el inversor

Verifica los números de programa en el manual de tu firmware; en la serie VM II suelen ser los siguientes.

- Prioridad de salida **SBU**.
- SOC/tensión de **vuelta a red: 20 %** (programa 12). SOC de **vuelta a batería: 30 %** (programa 13; hoy está en ~50 %).
- Prioridad del cargador **solo solar (OSO)** mientras la tarifa sea plana (BT1). Tus datos muestran que ya no carga desde la red. Solo cambiar a “solar + red” una noche para la carga de calibración cuando el panel la pida.
- **Junio y julio: 40/50.** Resto del año: 20/30. Con temporal anunciado, subir temporalmente a 40/50.

## Pendientes de validar con más datos

- Escala del SOC: tras una carga completa, comprobar si la capacidad aparente se acerca a los 15,36 kWh de placa. Si no, el sensor de corriente del inversor está midiendo bajo y conviene contrastar con el BMS.
- Geometría: configurada como PV1 25° y PV2 40°, ambos a 90° (este). Si la orientación no es exactamente este, ajustar `PV1_AZIMUTH`/`PV2_AZIMUTH`. El panel compara cada día el “solar esperado” con lo real; el 19-oct, con solo PV2, se midió justo la mitad de lo esperado para ambos strings.
- Consumo de invierno: hoy se extrapola (+25 %). El estudio usará el consumo real de cada mes a medida que exista.
- Tarifa real de tu boleta (`GRID_TARIFF_CLP_KWH`) y precio de la batería para el desgaste (`BATTERY_WEAR_CLP_KWH` ≈ precio ÷ (ciclos × kWh × profundidad)).
