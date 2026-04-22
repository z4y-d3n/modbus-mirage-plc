FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY modbus_mirage.py .

EXPOSE 502

CMD ["python", "modbus_mirage.py", "--ip", "0.0.0.0", "--port", "502", "--quiet"]