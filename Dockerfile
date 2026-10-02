# IRCart - Developed by acidvegas in Python (https://git.supernets.org/ircart)
# Dockerfile
FROM python:3-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV HOME=/tmp
EXPOSE 9009
# Single worker so the in-memory art index & background scans exist once; threads handle concurrency.
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:9009", "--access-logfile", "-", "app:app"]
