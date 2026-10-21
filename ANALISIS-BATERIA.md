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
5. **Con temporal anunciado**, fuera de junio–julio, conviene subir temporalmente a 40/50. El panel avisa con viento ≥ 50 km/h o lluvia ≥ 25 mm, y alerta si pasan 10 días sin carga completa.
6. **El sol perdido es enorme pero difícil de aprovechar**: ~6.200 kWh/año (≈ 58 % del potencial, casi todo de octubre a marzo), porque la batería se llena y no hay exportación. Con la batería de 15 kWh, mover consumo a la mañana ya solo ahorra ~30 kWh/año: la batería cubre casi todo. Ese excedente solo rinde exportándolo (net billing, Ley 20.571, con inversor/configuración que inyecte y declaración TE4) o con cargas nuevas en horas de sol que reemplacen gas o leña: termo eléctrico, bomba de calor o auto eléctrico.

## Ajustes sugeridos en el inversor

Verifica los números de programa en el manual de tu firmware; en la serie VM II suelen ser los siguientes.

- Prioridad de salida **SBU**.
- SOC/tensión de **vuelta a red: 20 %** (programa 12). SOC de **vuelta a batería: 30 %** (programa 13; hoy está en ~50 %).
- Prioridad del cargador **solo solar (OSO)** mientras la tarifa sea plana (BT1). Tus datos muestran que ya no carga desde la red.
- **Junio y julio: 40/50.** Resto del año: 20/30. Con temporal anunciado, subir temporalmente a 40/50.

## Pendientes de validar con más datos

- Escala del SOC: tras una carga completa, comprobar si la capacidad aparente se acerca a los 15,36 kWh de placa. Si no, el sensor de corriente del inversor está midiendo bajo y conviene contrastar con el BMS.
- Geometría: configurada como PV1 25° y PV2 40°, ambos a 90° (este). Si la orientación no es exactamente este, ajustar `PV1_AZIMUTH`/`PV2_AZIMUTH`. El panel compara cada día el “solar esperado” con lo real; el 19-oct, con solo PV2, se midió justo la mitad de lo esperado para ambos strings.
- Consumo de invierno: hoy se extrapola (+25 %). El estudio usará el consumo real de cada mes a medida que exista.
- Tarifa real de tu boleta (`GRID_TARIFF_CLP_KWH`) y precio de la batería para el desgaste (`BATTERY_WEAR_CLP_KWH` ≈ precio ÷ (ciclos × kWh × profundidad)).
