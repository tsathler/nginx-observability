FROM python:3.13.18-slim-trixie
RUN apt-get update && apt-get -y upgrade && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY receiver.py .
USER 10001:10001
EXPOSE 8081
CMD ["python", "-u", "receiver.py"]
