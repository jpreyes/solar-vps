# Análisis con datos reales · octubre 2026

Datos usados: historial de 5 min del inversor del 17 al 20 de octubre, lecturas en tiempo real del 20 al 21 de octubre y meteorología horaria de Open-Meteo. También 11 años (2015–2025) de radiación horaria de Valdivia sobre un plano a 35° orientado al norte (Open-Meteo archive, reanálisis ERA5). Con solo 4 días medidos, los valores del sistema se refinarán solos a medida que el VPS acumule datos. El panel recalcula todo cada hora.

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

Con tus 16 × 620 W (9,92 kWp) y máximo de 8 kW, la radiación de Valdivia da en promedio:

| Mes | Ene | Feb | Mar | Abr | May | Jun | Jul | Ago | Sep | Oct | Nov | Dic |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| kWh/día solar esperados | 53 | 50 | 43 | 30 | 22 | 17 | 19 | 25 | 34 | 42 | 46 | 51 |
| Día malo (percentil 10) | 39 | 31 | 20 | 10 | 6 | 3 | 4 | 5 | 12 | 19 | 24 | 32 |

Con ambos strings, incluso en junio el promedio (17 kWh/día) supera tu consumo. El invierno no es “sin sol”: es **muy variable**, con rachas de días de 3–6 kWh.

## ¿20/30 en verano y 40/50 en invierno?

Simulación hora a hora, 11 años de radiación, **ambos strings (9,92 kWp, tope 8 kW)**, **batería de 15,36 kWh**, tu consumo medido (11–13 kWh/día con +25 % en invierno) y el comportamiento real del modo red (la casa usa la red y el sol solo carga la batería). Eficiencias físicas: carga 95 %, descarga + inversor 92 %, consumo propio 50 W. Costo: red a $230/kWh más desgaste a $45/kWh entregado (ajustable).

| Umbrales | Red kWh/año | Autosuficiencia | Ciclos/año | Cambios red↔batería/año | Costo anual |
|---|---|---|---|---|---|
| 22/50 (actual) | 297 | 93,7 % | 120 | 68 | $151.000 |
| **20/30 todo el año** | **258** | **94,5 %** | 120 | 80 | **$143.000** |
| 30/40 | 297 | 93,7 % | 118 | 91 | $150.000 |
| 40/50 | 342 | 92,7 % | 116 | 107 | $159.000 |
| 20/30 verano · 40/50 invierno | 337 | 92,8 % | 116 | 104 | $158.000 |
| 20/30 verano · 30/40 invierno | 295 | 93,7 % | 118 | 90 | $150.000 |

Sensibilidad a un consumo de invierno mayor (perfil típico, sin el perfil medido):

| Consumo | 20/30 | 22/50 actual | 20/30 + 40/50 invierno | Sobrecosto del 40/50 invernal |
|---|---|---|---|---|
| 12 kWh/día, +25 % invierno | 458 kWh | 503 kWh | 657 kWh | ≈ $42.000/año |
| 14 kWh/día, +50 % invierno | 1.098 kWh | 1.232 kWh | 1.449 kWh | ≈ $68.000/año |
| 18 kWh/día, +50 % invierno | 2.037 kWh | 2.279 kWh | 2.357 kWh | ≈ $59.000/año |

Conclusiones:

1. **20/30 es lo más barato en todos los escenarios**, también en invierno. Con 15,36 kWh la batería cubre casi toda la noche: autosuficiencia ≈ 94 % con tu consumo actual.
2. **El cambio útil es bajar la vuelta a batería de 50 % a 30 %**: ahorra 40–240 kWh/año según el consumo. En modo red la casa compra todo a la red aunque haya sol.
3. **40/50 en invierno es un seguro, no un ahorro.** Cuesta ~80 kWh/año (≈ $15.000) con tu consumo actual, y hasta ≈ $40–70 mil si el consumo de invierno sube mucho. A cambio guarda **≈ 3 kWh más de reserva** (20 % de 15,36 kWh): unas 12–15 h de consumo base nocturno o 4–6 h de consumo normal durante un corte. Con una batería de este tamaño es un seguro razonable si los cortes en temporales te preocupan. La opción intermedia es dejar 20/30 y subir a 40/50 **solo cuando el panel anuncia temporal** (viento ≥ 50 km/h o lluvia ≥ 25 mm).
4. Ir más bajo (15/25) no vale la pena: el ahorro es marginal y aumenta la profundidad de descarga. 20 % es un buen piso, sobre todo mientras el SOC del BMS no esté calibrado.
5. **Carga completa periódica**: en junio y julio la batería no llega al 100 % muchos días, y el SOC del BMS se descalibra (el “20 %” deja de ser 20 %). El panel alerta tras 10 días; conviene forzar una carga completa. Ahora mismo también ayudaría a resolver la diferencia entre capacidad de placa y aparente.
6. **La palanca más grande sigue sin ser los umbrales**: con ambos strings se pierden ~6.000–8.000 kWh/año de sol (≈ 60 % del potencial, sobre todo de octubre a marzo), porque la batería se llena a mediodía y no hay exportación. Mover 3 kWh/día de consumo a 11–15 h (lavadora, secadora, termo, bomba de calor) ahorra ~300 kWh/año, más que cualquier cambio de umbral. Inyectar a la red (net billing, Ley 20.571) requeriría un inversor/configuración que exporte y la declaración TE4.

## Ajustes sugeridos en el inversor

Verifica los números de programa en el manual de tu firmware; en la serie VM II suelen ser los siguientes.

- Prioridad de salida **SBU**.
- SOC/tensión de **vuelta a red: 20 %** (programa 12). SOC de **vuelta a batería: 30 %** (programa 13; hoy está en ~50 %).
- Prioridad del cargador **solo solar (OSO)** mientras la tarifa sea plana (BT1). Tus datos muestran que ya no carga desde la red.
- Con temporal anunciado: subir temporalmente a 40/50 y volver a 20/30 después.

## Pendientes de validar con más datos

- Escala del SOC: tras una carga completa, comprobar si la capacidad aparente se acerca a los 15,36 kWh de placa. Si no, el sensor de corriente del inversor está midiendo bajo y conviene contrastar con el BMS.
- Orientación e inclinación de los paneles: ajustar `PV_TILT` y `PV_AZIMUTH`. Con solo PV2, los ratios de la mañana sugieren paneles más hacia el este o más inclinados que 35° norte. El panel compara “solar esperado” con lo real cada día.
- Consumo de invierno: hoy se extrapola (+25 %). El estudio usará el consumo real de cada mes a medida que exista.
- Tarifa real de tu boleta (`GRID_TARIFF_CLP_KWH`) y precio de la batería para el desgaste (`BATTERY_WEAR_CLP_KWH` ≈ precio ÷ (ciclos × kWh × profundidad)).
