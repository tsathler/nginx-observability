FROM python:3.13.18-slim-trixie
RUN apt-get update && apt-get -y upgrade && rm -rf /var/lib/apt/lists/*
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip /usr/local/lib/python3.13/site-packages/pip-*.dist-info /usr/local/lib/python3.13/ensurepip
WORKDIR /app
COPY receiver.py .
USER 10001:10001
EXPOSE 8081
CMD ["python", "-u", "receiver.py"]
