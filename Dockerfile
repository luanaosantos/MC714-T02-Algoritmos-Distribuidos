FROM python:3.12-slim
WORKDIR /projeto
COPY app/ ./app/
CMD ["python", "-u", "-m", "app.main"]
