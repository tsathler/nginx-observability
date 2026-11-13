FROM python:3.13.2-slim
WORKDIR /app
COPY receiver.py .
USER 10001:10001
EXPOSE 8081
CMD ["python", "-u", "receiver.py"]
