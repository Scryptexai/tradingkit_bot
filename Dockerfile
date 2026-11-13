FROM python:3.12-slim
WORKDIR /opt/quantlab
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 QUANTLAB_DB=/data/quantlab.sqlite3
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
RUN mkdir -p /data && useradd --create-home --uid 10001 quantlab && chown -R quantlab:quantlab /data /opt/quantlab
USER quantlab
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
