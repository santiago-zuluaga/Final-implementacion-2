# Informe de caché y rendimiento Redis

## Método

Se ejecutó `python scripts/benchmark_cache.py` contra Docker Compose el 18 de noviembre de 2026. El script fuerza 10 misses por cada uno de los tres productos de demo eliminando solo las claves `products:v1:{id}`, mide 30 lecturas desde el cliente HTTP, luego mide 200 lecturas con claves calientes. Consulta el delta de contadores de `/cache/metrics` y toma `docker stats --no-stream` de Productos, PostgreSQL y Redis antes y después. El JSON completo se conserva en [`artifacts/redis_benchmark.json`](../artifacts/redis_benchmark.json).

## Resultado de la corrida

| Tipo | Solicitudes | p50 cliente (ms) | p95 cliente (ms) | Mín–máx (ms) |
|---|---:|---:|---:|---:|
| Miss (PostgreSQL y repoblar Redis) | 30 | 4.303 | 6.290 | 3.569–13.936 |
| Hit (Redis) | 200 | 1.743 | 2.991 | 1.392–3.539 |

Los contadores de esa ventana registraron 200 hits, 30 misses y 0 fallbacks; la tasa de hit de la mezcla de prueba fue 87.0%. La mediana observada de hit fue 59.5% menor que la mediana de miss. Es evidencia direccional de esta ejecución local, no una promesa de mejora general.

El endpoint midió p50 interno de 0.361 ms y p95 de 2.428 ms en la ventana del proceso; esos contadores son locales a una instancia y se reinician al reiniciar Productos. Para comparar, se conserva también el tiempo medido desde el cliente HTTP.

## Uso de recursos observado

Snapshots instantáneos de Docker (no promedios durante toda la carga):

| Contenedor | CPU antes | CPU después | Memoria antes | Memoria después |
|---|---:|---:|---:|---:|
| Productos | 20.01% | 19.07% | 97.85 MiB | 97.70 MiB |
| PostgreSQL | 2.83% | 0.51% | 31.01 MiB | 34.80 MiB |
| Redis | 0.75% | 0.41% | 4.863 MiB | 5.238 MiB |

Las lecturas concurrentes no se generaron; por eso los porcentajes CPU son solo muestras al tomar el snapshot y no atribuyen causalidad al benchmark. Memoria y CPU dependen del host Docker y de otros procesos activos.

## Fallback y límites

En una prueba separada se detuvo Redis de forma controlada. Tres peticiones a Productos continuaron respondiendo desde PostgreSQL: 379.2, 5.3 y 2.9 ms desde cliente; se contaron fallbacks. El primer intento tiene espera máxima de 350 ms para Redis; un circuito de cinco segundos envía solicitudes consecutivas directamente a PostgreSQL. Después del reinicio, una lectura produjo miss y la siguiente hit. El TTL configurado es 300 s; se aceleró a 1 s únicamente para verificar expiración.

La corrida es secuencial, breve y de baja concurrencia. No representa capacidad máxima, latencia de red externa ni operación de producción. No se midió memoria de cada petición, ni se ejecutó un control con Redis deshabilitado para comparar bajo carga equivalente. Para repetirla, levanta el stack y el seeder primero; se modifican únicamente las tres claves de caché de demo y el JSON de resultado se sobrescribe.
