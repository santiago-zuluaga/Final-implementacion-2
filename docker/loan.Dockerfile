FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY domain_service ./domain_service
COPY loan_service ./loan_service
COPY models ./models
COPY artifacts/drift_report.json ./artifacts/drift_report.json
EXPOSE 8000
CMD ["uvicorn","domain_service.app:app","--host","0.0.0.0","--port","8000"]
