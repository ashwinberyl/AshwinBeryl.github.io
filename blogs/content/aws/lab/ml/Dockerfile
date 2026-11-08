FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/program:${PATH}"
WORKDIR /opt/program

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY preprocess.py train.py serve.py train serve ./
RUN chmod +x train serve
