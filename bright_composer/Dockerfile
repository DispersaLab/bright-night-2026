FROM python:3.12-slim

WORKDIR /app/bright_composer
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["python", "compose_daemon.py", "--path", "/app/bright_composer/bright"]
