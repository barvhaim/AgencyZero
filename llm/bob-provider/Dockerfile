FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir flask requests

COPY proxy-apikey.py .

RUN useradd --system --no-create-home bob
USER bob

EXPOSE 8989
CMD ["python", "proxy-apikey.py"]
