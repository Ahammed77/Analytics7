FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY a7chat ./a7chat
COPY config ./config
COPY catalogue ./catalogue
EXPOSE 8000
CMD ["uvicorn", "--factory", "a7chat.api:create_app", "--host", "0.0.0.0", "--port", "8000"]
