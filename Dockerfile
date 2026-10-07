FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home pacs && mkdir -p /data/uploads && chown -R pacs:pacs /data
COPY --chown=pacs:pacs portal ./portal
COPY --chown=pacs:pacs scripts ./scripts
USER pacs
EXPOSE 8000
CMD ["uvicorn","portal.app:create_from_env","--factory","--host","0.0.0.0","--port","8000","--no-proxy-headers","--no-access-log"]
