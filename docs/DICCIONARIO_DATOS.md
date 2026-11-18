# Diccionario de datos

Los archivos son datos sintéticos entregados para el ejercicio. `prestamos_entrenamiento.csv` tiene 12.000 filas y 15 columnas; `solicitudes_nuevas.csv`, 200 filas y 14 columnas. Ambos comparten los campos de solicitud descritos abajo; el archivo nuevo omite la etiqueta.

| Columna | Tipo esperado | Unidad / dominio | Uso |
|---|---|---|---|
| `solicitud_id` | texto | identificador único de solicitud | Trazabilidad; se excluye del modelo. |
| `cliente_id` | texto | identificador de cliente | Enlace de registros; se excluye del modelo. |
| `ingresos_mensuales_cop` | entero | COP por mes | Predictor. |
| `obligaciones_mensuales_cop` | entero | COP por mes | Predictor. |
| `tipo_empleo` | categoría nullable | `dependiente`, `independiente`, `temporal` | Predictor categórico; se imputa con categoría más frecuente. |
| `antiguedad_laboral_meses` | número nullable | meses | Predictor; imputación mediana. |
| `meses_historial_crediticio` | número nullable | meses | Predictor; imputación mediana. |
| `creditos_previos` | entero | cantidad de créditos previos | Predictor. |
| `atrasos_previos_30d` | entero | cantidad de atrasos reportados en ventana de 30 días | Predictor. |
| `porcentaje_pago_puntual` | número nullable | porcentaje de 0 a 100 | Predictor; se deriva también el indicador `sin_historial`. |
| `monto_solicitado_cop` | entero | COP | Predictor. |
| `plazo_meses` | entero | meses | Predictor. |
| `tasa_mensual_simulada` | número | tasa mensual sintética del escenario | Constante en el histórico; documentada, pero excluida del modelo. |
| `cuota_estimada_cop` | número | COP por mes | Predictor. |
| `incumplimiento_90d` | entero binario | 1: incumplimiento dentro de 90 días; 0: no incumplimiento | Etiqueta disponible solo en entrenamiento; nunca es predictor. |

El pipeline deriva `sin_historial`, `ratio_endeudamiento = (obligaciones + cuota estimada) / ingresos` y `cuota_ingreso = cuota estimada / ingresos`. El identificador, la tasa constante y la etiqueta no entran en `FEATURES`. Las transformaciones se ajustan dentro del pipeline usando solo train.

## Auditoría reproducible

Ejecuta `python ml/audit_data.py`. El resumen completo de tipos, faltantes, cardinalidad, duplicados, rangos numéricos, clases e identificadores se guarda en [`artifacts/data_audit.json`](../artifacts/data_audit.json), junto con el SHA-256 de cada archivo. La auditoría no modifica los CSV ni entrena un modelo.
