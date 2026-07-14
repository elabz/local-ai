FROM nvidia/cuda:12.6.3-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY metering_proxy.py gpu_exporter.py ./
ENTRYPOINT ["python3"]
