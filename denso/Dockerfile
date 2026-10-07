# Small image for the DENSO side services: data pipeline jobs, Agent Gateway,
# free-tier rate proxy. The LightRAG server itself uses the repository's Dockerfile.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY denso/requirements.docker.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# denso/ is bind-mounted by docker-compose so data and results stay on the host;
# the copy below only makes the image usable on its own.
COPY denso/ /app/denso/

EXPOSE 9700 8899
CMD ["python", "denso/gateway/app.py"]
