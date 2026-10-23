FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

WORKDIR /app
RUN pip install --no-cache-dir fastmcp==4.1.3

COPY server.py .

RUN useradd --system --no-create-home mcp
USER mcp

EXPOSE 8000
CMD ["python", "server.py"]
