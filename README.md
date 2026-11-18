# CrediMarket

Implementación académica del enunciado de CrediMarket. Los datos son sintéticos y el modelo es una demostración de ingeniería, no una política de crédito real.

## Estado inicial

El repositorio se inicia desde cero. Están disponibles el enunciado, el histórico de 12.000 filas y 200 solicitudes sin etiqueta. Se verificaron tamaños, columnas y faltantes; el CSV de solicitudes no sirve para medir clasificación. El entorno local tiene Python 3.14, pandas, scikit-learn y joblib; Docker está instalado. MLflow y FastAPI no están instalados, Java sí. Para reproducir se propone Python 3.12 en contenedores, evitando depender del entorno local.

## Componentes

La estructura contiene el proceso offline de entrenamiento y el servicio Python de Préstamos. La arquitectura objetivo conserva cuatro dominios: Productos (Redis), Clientes (importación), Préstamos (FastAPI + modelo) e Inventario (reserva atómica), con PostgreSQL, RabbitMQ y MLflow como infraestructura. Los detalles de integración, seguridad y frontend siguen pendientes de implementación.

## Reproducción del modelo

Coloque los dos CSV entregados por el curso en `data/`. Ejecute `python -m venv .venv`, active el entorno, `pip install -r requirements.txt`, y `python ml/train.py`. El entrenamiento imprime hash, particiones y métricas, registra las corridas en MLflow si está disponible, y exporta versiones identificadas bajo `models/`. Promoción: `python ml/promote.py v1` (o la versión indicada por el entrenamiento). La API carga la versión promovida, no el último archivo.

Para iniciar la API: `uvicorn loan_service.app:app --reload`. La API de negocio, persistencia, broker y frontend aún no están integrados.

## Integrantes

| Integrante | Responsabilidades |
|---|---|
| Por definir | Por definir |

