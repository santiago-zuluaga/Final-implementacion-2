# Verificación inicial y pendientes

## Disponibilidad comprobada

| Elemento | Resultado |
|---|---|
| Enunciado | Leído; define cuatro servicios, frontend, RabbitMQ o Kafka, Redis, MLOps y 16 pruebas. |
| Histórico | Disponible, 12.000 × 15; etiqueta `incumplimiento_90d`; pago puntual tiene 2.473 nulos y empleo/antigüedad/historial también presentan faltantes. |
| Solicitudes | Disponible, 200 × 14, sin etiqueta; solo inferencia/equivalencia. |
| Repo | Inicialmente vacío, sin Git inicializado. |
| Entorno | Docker y Java disponibles; pandas, scikit-learn, joblib presentes; MLflow/FastAPI no están instalados localmente. |

El código de entrenamiento valida la presencia de la etiqueta, separa 60/20/20 estratificado con semilla fija, ajusta preprocesamiento dentro del pipeline, compara baseline y siete candidatos. Define AP como métrica principal, ROC-AUC como desempate, selecciona el umbral por costo ficticio en validación y consulta el test una vez al final. El manifiesto y la promoción explícita son parte del código. Para que MLflow esté operativo hay que instalar `requirements.txt` y levantar el tracking server.

## Brecha entre el pedido y lo entregado hasta ahora

La base implementada cubre el flujo inicial de datos/modelo y el endpoint de predicción, no constituye el proyecto completo del enunciado. Faltan cuatro servicios desplegables y sus BDs, RabbitMQ con outbox/reintentos/DLQ, Redis cache-aside y mediciones, CRUD y reservas atómicas, autenticación/autorización, endpoints de negocio e idempotencia durable, drift/segunda versión/rollback, equivalencia con las 200 solicitudes, frontend, compose, pruebas de aceptación e integrantes reales.

El análisis pegado es una propuesta previa, no un requisito del usuario. Se sigue el enunciado como fuente normativa. En particular la autenticación está marcada opcional en secciones 9 y 10, aunque la rúbrica premia roles/autorización y el caso 13; la implementaremos como necesaria para la mejor cobertura, sin presentarla como obligatoria textual.

