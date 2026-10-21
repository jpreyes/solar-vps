# Análisis con datos reales · octubre 2026

Datos usados: historial de 5 min del inversor del 17 al 20 de octubre, lecturas en tiempo real del 20 al 21 de octubre y meteorología horaria de Open-Meteo. También 11 años (2015–2025) de radiación horaria de Valdivia sobre un plano a 35° orientado al norte (Open-Meteo archive, reanálisis ERA5). Con solo 4 días medidos, los valores del sistema se refinarán solos a medida que el VPS acumule datos. El panel recalcula todo cada hora.

## Lo que muestran tus datos

| Hallazgo | Evidencia | Consecuencia |
|---|---|---|
| Configuración actual ≈ **22/50** | Pasa a red con SOC 19–23 %; volvió a batería recién al 50 % (20-oct 10:37) | La casa queda en red por la mañana aunque haya sol |
| En modo red (L) **la casa consume de la red y el sol solo carga la batería** | 20-oct 09:00: solar 1.984 W → batería 1.945 W; carga 179 W desde la red | El umbral de retorno (el “50”) sí cuesta energía |
| `gridPowerInputActiveTotal` **no es importación en modo batería** | En modo B copia el consumo (1.333 W vs 1.376 W) con `statusGrid=0` | El panel antiguo decía “la red aporta” cuando no era así (corregido) |
| No carga la batería desde la red | Noches en modo L con SOC estable 19→18 % | Correcto con tarifa plana: cargar desde la red solo pierde ~20 % |
| Batería ≈ **10,5–11 kWh** por cada 100 % de SOC | Descarga integrada vs caída de SOC | Rendimiento ida y vuelta medido ≈ 77–80 % |
| Consumo propio del inversor ≈ **50 W** | Descarga de batería − consumo, de noche | ≈ 1,2 kWh/día |
| Consumo de la casa ≈ **11–15 kWh/día** | Días completos 18–20 oct | Base nocturna 100–250 W y picos de 2–4 kW al atardecer |
| **String PV1 sin tensión ~90 % del tiempo** | `pvInputVoltage1` = 0 V con sol en PV2 | Producción ≈ mitad del arreglo (problema conocido, en reparación) |
| BMS desconectado el 19-oct 10:50 | SOC 0 % y 31 V durante 2 lecturas, paso forzado a red | Probablemente durante la instalación de PV1; el panel ahora lo alerta |
| La hora del equipo es correcta | El solar arranca 07:00 y sigue la irradiancia horaria (UTC−3) | Se pueden cruzar con el clima sin corrección |
| **Se pierde sol a mediodía** | 18-oct: batería al 100 % a las 12:00 y el solar cae de 4 kW al consumo (~0,8 kW) | Sin exportación, el excedente se pierde |

Con tus 16 × 620 W (9,92 kWp) y máximo de 8 kW, la radiación de Valdivia da en promedio:

| Mes | Ene | Feb | Mar | Abr | May | Jun | Jul | Ago | Sep | Oct | Nov | Dic |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| kWh/día solar esperados | 53 | 50 | 43 | 30 | 22 | 17 | 19 | 25 | 34 | 42 | 46 | 51 |
| Día malo (percentil 10) | 39 | 31 | 20 | 10 | 6 | 3 | 4 | 5 | 12 | 19 | 24 | 32 |

Incluso en junio el promedio (17 kWh/día) supera tu consumo. El invierno no es “sin sol”: es **muy variable**, con rachas de días de 3–6 kWh.

## ¿20/30 en verano y 40/50 en invierno?

Simulación hora a hora, 11 años, batería de 10,5 kWh, tu consumo medido (con +25 % en invierno) y el comportamiento real del modo red. Costo: red a $230/kWh más desgaste de batería a $45/kWh entregado (ajustable).

| Umbrales | Red kWh/año | Ciclos/año | Cambios red↔batería/año | Costo anual |
|---|---|---|---|---|
| 22/50 (actual) | 446 | 167 | 131 | $181.000 |
| **20/30 todo el año** | **391** | 165 | 144 | **$168.000** |
| 30/40 | 467 | 162 | 232 | $184.000 |
| 40/50 | 593 | 154 | 346 | $209.000 |
| 20/30 verano · 40/50 invierno | 582 | 155 | 337 | $207.000 |
| 20/30 verano · 30/40 invierno | 463 | 163 | 231 | $183.000 |

Sensibilidad (consumo de 14 kWh/día, +25 % o +50 % en invierno): el orden no cambia. 20/30 queda 10–15 % por debajo de 20/50, y el esquema 20/30 + 40/50 invernal consume 250–300 kWh/año más de red que 20/30 todo el año.

Conclusiones:

1. **20/30 es lo más barato todo el año**, también en invierno. Subir el mínimo en invierno no ahorra: deja sin usar batería que el sol sí alcanza a llenar en muchos días (en junio y julio la batería llega al 100 % en ~40 % de los días).
2. **Bajar el retorno de 50 a 30 es el cambio útil**: con tu inversor, mientras está en modo red la casa compra todo a la red aunque haya sol.
3. **40/50 en invierno es un seguro, no un ahorro.** Cuesta unos $35–40 mil al año y guarda ~2–3 kWh de reserva (3–6 h de consumo nocturno) para cortes de luz, frecuentes en temporales de Valdivia. Si los cortes te importan, es más barato subir el mínimo **solo cuando hay temporal pronosticado**: el panel avisa con viento ≥50 km/h o lluvia ≥25 mm.
4. Ir más bajo (15/25) ahorra un poco más, pero lleva el LiFePO4 a 85 % de profundidad de descarga y deja poca reserva. 20 % es un buen piso para la vida útil y para el error del SOC del BMS.
5. **Carga completa periódica**: en invierno pueden pasar 10–20 días sin llegar al 100 %, y el SOC del BMS se descalibra (el “20 %” deja de ser 20 %). El panel alerta tras 10 días; en ese caso conviene una carga completa.
6. **La palanca más grande no son los umbrales**: se pierden ~7.500–8.000 kWh/año de solar (≈60 % del potencial, sobre todo de octubre a marzo). Mover 3 kWh/día de consumo a 11–15 h (lavadora, secadora, termo eléctrico, bomba de calor) ahorra ~300–380 kWh/año de red, más que cualquier cambio de umbral. Inyectar a la red (net billing, Ley 20.571) requeriría un inversor/configuración que exporte y la declaración TE4.

## Ajustes sugeridos en el inversor

Verifica los números de programa en el manual de tu firmware; en la serie VM II suelen ser los siguientes.

- Prioridad de salida **SBU**.
- SOC/tensión de **vuelta a red: 20 %** (programa 12). SOC de **vuelta a batería: 30 %** (programa 13; hoy está en ~50 %).
- Prioridad del cargador **solo solar (OSO)** mientras la tarifa sea plana (BT1). Tus datos muestran que ya no carga desde la red.
- Con temporal anunciado: subir temporalmente a 40/50 y volver a 20/30 después.

## Pendientes de validar con más datos

- Capacidad real de la batería: confirmar con la placa (Ah × V) y con 2–3 semanas de datos.
- Orientación e inclinación de los paneles: ajustar `PV_TILT` y `PV_AZIMUTH`. Con solo PV2, los ratios de la mañana sugieren paneles más hacia el este o más inclinados que 35° norte. El panel compara “solar esperado” con lo real cada día.
- Consumo de invierno: hoy se extrapola (+25 %). El estudio usará el consumo real de cada mes a medida que exista.
- Tarifa real de tu boleta (`GRID_TARIFF_CLP_KWH`) y precio de la batería para el desgaste (`BATTERY_WEAR_CLP_KWH` ≈ precio ÷ (ciclos × kWh × profundidad)).
