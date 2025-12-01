FROM python:3.13-slim

WORKDIR /app

COPY requirements.docker.txt .

RUN pip install --no-cache-dir -r requirements.docker.txt

COPY . .

EXPOSE 9001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001"]