# Decisiones técnicas

- Se eligió RabbitMQ por su patrón de cola punto a punto, pocos consumidores y falta de requerimiento de replay analítico. Kafka se justificaría si se necesitara conservar/reproducir logs, numerosos consumidores independientes o mayor caudal.
- Los cuatro dominios se ejecutan como contenedores FastAPI independientes con roles y bases separados; Préstamos es el único que incluye artefactos de ML en su imagen. El enunciado exige Python para Préstamos y no obliga Java para los demás. El stack Spring sugerido en el análisis anterior era propuesta, no requisito.
- Una instancia PostgreSQL crea cinco bases independientes con credenciales separadas (cuatro servicios y MLflow), reduciendo recursos locales sin compartir tablas.
- Modelo v1 es la selección final de AP sobre validación con desempate por ROC-AUC. v2 es el siguiente candidato por validación para demostrar promoción/rollback; el test no se consulta para v2.
- Se elige cuota francesa mensual al 1,8 %, igual que el dataset sintético. Los costos de error (5 falso aprobado, 1 falso rechazo) son inventados para el ejercicio y no son política crediticia.
- El frontend se sirve con Nginx y proxy interno para no exponer los puertos de infraestructura al navegador.
