FROM python:3.13.18-slim-trixie
RUN apt-get update && apt-get -y upgrade && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY generate.py .
USER 10001:10001
CMD ["python", "-u", "generate.py"]
