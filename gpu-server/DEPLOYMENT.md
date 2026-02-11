# GPU Server Deployment Guide

Complete guide for deploying HeartCode GPU inference servers to any hardware with NVIDIA GPUs.

## Table of Contents

1. [Hardware Requirements](#hardware-requirements)
2. [Initial Server Setup](#initial-server-setup)
3. [First-Time Deployment](#first-time-deployment)
4. [Model Management](#model-management)
5. [Scaling GPUs](#scaling-gpus)
6. [Monitoring & Maintenance](#monitoring--maintenance)
7. [Troubleshooting](#troubleshooting)
8. [Performance Tuning](#performance-tuning)

---

## Hardware Requirements

### Minimum Requirements

- **GPU**: NVIDIA GPU with 6GB+ VRAM
  - Pascal (GTX 1060 6GB, P106-100, P104-100) or newer
  - Compute Capability 6.0 or higher
- **CPU**: Any x86-64 processor (AVX support optional)
- **RAM**: 8GB minimum, 16GB recommended
- **Storage**: 20GB free space (10GB for Docker images, 5GB+ for models)
- **OS**: Ubuntu 20.04+ or any Linux with Docker support

### Tested Configurations

| GPU Model | VRAM | Recommended Model Size | Tested Quantization |
|-----------|------|------------------------|---------------------|
| P106-100 | 6GB | Up to 8B | Q4_K_M |
| P104-100 | 8GB | Up to 8B | Q4_K_M, Q5_K_M |
| RTX 3060 | 12GB | Up to 13B | Q5_K_M |
| RTX 4090 | 24GB | Up to 70B | Q4_K_M |

---

## Initial Server Setup

### 1. Install NVIDIA Drivers

```bash
# Check if drivers are installed
nvidia-smi

# If not installed, install drivers (Ubuntu)
sudo apt update
sudo apt install -y nvidia-driver-535  # Or latest version
sudo reboot

# Verify installation
nvidia-smi
```

Expected output:
```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 535.xx.xx    Driver Version: 535.xx.xx    CUDA Version: 12.2   |
|-------------------------------+----------------------+----------------------+
| GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
| Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
...
```

### 2. Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
```

### 3. Install NVIDIA Container Toolkit

```bash
# Add NVIDIA repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# Install nvidia-docker2
sudo apt update
sudo apt install -y nvidia-docker2

# Restart Docker
sudo systemctl restart docker

# Test GPU access from Docker
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

If the test command shows your GPUs, you're ready to proceed!

---

## First-Time Deployment

### 1. Clone/Copy the GPU Server Code

```bash
# On your local machine (where you have the code)
cd /path/to/heartcode
tar -czf gpu-server.tar.gz gpu-server/

# Copy to target server
scp gpu-server.tar.gz user@target-server:~/

# On target server
cd ~
tar -xzf gpu-server.tar.gz
cd gpu-server
```

### 2. Download a Model

Choose a model based on your GPU VRAM:

#### Option A: Using wget (direct download)

```bash
cd ~/gpu-server
mkdir -p models
cd models

# Example: Llama 3.2 3B Q4_K_M (2.3GB, needs ~3.5GB VRAM)
wget https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf -O model.gguf

# Example: Mistral 7B Q4_K_M (4.4GB, needs ~5.5GB VRAM)
wget https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf -O model.gguf

# Example: NeuralDaredevil 8B Q4_K_M (4.6GB, needs ~5.8GB VRAM)
wget 'https://huggingface.co/QuantFactory/NeuralDaredevil-8B-abliterated-GGUF/resolve/main/NeuralDaredevil-8B-abliterated.Q4_K_M.gguf?download=true' -O model.gguf
```

#### Option B: Using huggingface-cli

```bash
# Install huggingface_hub
pip install huggingface_hub

# Download model
huggingface-cli download bartowski/Llama-3.2-3B-Instruct-GGUF \
  Llama-3.2-3B-Instruct-Q4_K_M.gguf \
  --local-dir ~/gpu-server/models \
  --local-dir-use-symlinks False

# Rename to model.gguf
mv ~/gpu-server/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf ~/gpu-server/models/model.gguf
```

### 3. Verify Model File

```bash
cd ~/gpu-server
ls -lh models/model.gguf

# Should show something like:
# -rw-rw-r-- 1 user user 4.6G Jan  4 00:09 models/model.gguf
```

### 4. Configure for Your GPU Count

**If you have fewer than 8 GPUs**, edit `docker-compose.yml`:

```bash
# Check how many GPUs you have
nvidia-smi --query-gpu=count --format=csv,noheader | head -1

# Edit docker-compose.yml and remove/comment out extra GPU servers
# Keep only gpu-server-1 through gpu-server-N (where N is your GPU count)
nano docker-compose.yml
```

**If you have more than 8 GPUs**, add more services following the pattern.

### 5. Build and Start

```bash
cd ~/gpu-server

# Build Docker images (this takes 15-30 minutes for first build)
docker compose build

# Start all services
docker compose up -d

# Watch logs
docker compose logs -f
```

### 6. Verify Deployment

```bash
# Check all services are healthy
docker compose ps

# Test GPU server 1
curl http://localhost:8080/health

# Test LiteLLM proxy
curl http://localhost:4000/health

# Test inference (replace with your server IP)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-local-ai-dev" \
  -d '{
    "model": "heartcode-chat",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'
```

---

## Model Management

### Finding Models

**Recommended GGUF Model Sources:**

1. **HuggingFace GGUF Collections:**
   - [TheBloke's GGUF Models](https://huggingface.co/TheBloke)
   - [bartowski's GGUF Models](https://huggingface.co/bartowski)
   - [QuantFactory](https://huggingface.co/QuantFactory)

2. **Model Search:**
   - Search "model-name GGUF" on HuggingFace
   - Look for Q4_K_M or Q5_K_M quantizations

### Understanding Quantization

| Quantization | Size vs FP16 | Quality | VRAM Usage | Use Case |
|--------------|--------------|---------|------------|----------|
| Q2_K | ~25% | Lower | Minimal | Constrained VRAM |
| Q4_0 | ~50% | Good | Low | General use |
| **Q4_K_M** | ~50% | **Very Good** | **Balanced** | **Recommended** |
| Q5_K_M | ~60% | Better | Higher | 8GB+ VRAM |
| Q6_K | ~70% | Best | High | 12GB+ VRAM |
| Q8_0 | ~90% | Near-FP16 | Very High | 16GB+ VRAM |

**General Rule:** For an N-billion parameter model, Q4_K_M will be approximately N/2 GB in size.

### Switching Models (On Running Server)

#### Method 1: Quick Switch (No Rebuild)

```bash
cd ~/gpu-server/models

# Backup current model
mv model.gguf model.gguf.backup

# Download new model
wget <MODEL_URL> -O model.gguf

# Restart all GPU servers to load new model
docker compose restart gpu-server-1 gpu-server-2 gpu-server-3 \
  gpu-server-4 gpu-server-5 gpu-server-6 gpu-server-7 gpu-server-8

# Watch logs to confirm model loads
docker compose logs -f gpu-server-1
```

Model loading takes 30-60 seconds. Watch for:
```
llama.cpp server is ready
GPU Server gpu-1 started successfully
```

#### Method 2: Multiple Models (Switch by Symlink)

```bash
cd ~/gpu-server/models

# Download multiple models
wget <MODEL1_URL> -O llama-3.2-3b.gguf
wget <MODEL2_URL> -O mistral-7b.gguf
wget <MODEL3_URL> -O neural-8b.gguf

# Create symlink to active model
ln -sf llama-3.2-3b.gguf model.gguf

# To switch models:
ln -sf mistral-7b.gguf model.gguf
docker compose restart gpu-server-{1..8}
```

### Verifying Model After Switch

```bash
# Check logs for model loading
docker compose logs gpu-server-1 | grep "llama.cpp server is ready"

# Test inference
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "model",
    "messages": [{"role": "user", "content": "What model are you?"}],
    "max_tokens": 50
  }'
```

---

## Scaling GPUs

### Adding More GPUs

If you add GPUs to your server later:

1. **Update docker-compose.yml:**

```yaml
# Add new service (copy from existing and modify)
gpu-server-9:
  build:
    context: .
    dockerfile: Dockerfile
  container_name: local-ai-gpu-9
  runtime: nvidia
  environment:
    - NVIDIA_VISIBLE_DEVICES=8  # New GPU index
    - MODEL_PATH=/models/model.gguf
    - N_GPU_LAYERS=33
    - N_CTX=4096
    - N_BATCH=512
    - N_THREADS=4
    - PORT=8080
    - SERVER_ID=gpu-9
  volumes:
    - ./models:/models:ro
    - ./configs:/app/configs:ro
  ports:
    - "8088:8080"  # New external port
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            device_ids: ['8']  # New GPU device ID
            capabilities: [gpu]
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 120s
  restart: unless-stopped
```

2. **Update LiteLLM config** (`configs/litellm_config.yaml`):

```yaml
# Add new model entry
- model_name: "heartcode-chat"
  litellm_params:
    model: "openai/model"
    api_base: "http://gpu-server-9:8080/v1"
    api_key: "sk-local"
    max_tokens: 512
    temperature: 0.8
  model_info:
    id: "local-ai-gpu9"
    mode: "chat"
```

3. **Update Prometheus config** (`configs/prometheus.yml`):

```yaml
- job_name: 'gpu-server-9'
  static_configs:
    - targets: ['gpu-server-9:9091']
  metrics_path: /metrics
  scrape_interval: 10s
```

4. **Update depends_on in docker-compose.yml** for LiteLLM:

```yaml
litellm-proxy:
  depends_on:
    # ... existing ...
    gpu-server-9:
      condition: service_healthy
```

5. **Start the new server:**

```bash
docker compose up -d gpu-server-9
docker compose restart litellm-proxy prometheus
```

### Removing GPUs

If you need to reduce GPU count:

```bash
# Stop and remove services
docker compose stop gpu-server-8
docker compose rm -f gpu-server-8

# Update docker-compose.yml (remove or comment out gpu-server-8)
# Update configs/litellm_config.yaml (remove gpu-server-8 entry)
# Update configs/prometheus.yml (remove gpu-server-8 job)

# Restart dependent services
docker compose restart litellm-proxy prometheus
```

---

## Monitoring & Maintenance

### Checking System Status

```bash
# All services status
docker compose ps

# Resource usage
docker stats

# GPU utilization
nvidia-smi

# Continuous monitoring
watch -n 1 nvidia-smi
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f gpu-server-1

# Last N lines
docker compose logs --tail=100 gpu-server-1

# Follow specific errors
docker compose logs -f gpu-server-1 | grep ERROR
```

### Prometheus Metrics

Access Prometheus at `http://<server-ip>:9090`

**Useful Queries:**

```promql
# GPU memory usage
gpu_memory_used_bytes{gpu_id="0"}

# GPU utilization
gpu_utilization_percent{gpu_id="0"}

# GPU temperature
gpu_temperature_celsius{gpu_id="0"}

# Request rate (requests per second)
rate(inference_requests_total[1m])

# Request duration (95th percentile)
histogram_quantile(0.95, rate(inference_duration_seconds_bucket[5m]))

# Active requests
active_requests
```

### Regular Maintenance

**Weekly:**
```bash
# Check disk space
df -h

# Clean up old Docker resources
docker system prune -f
```

**Monthly:**
```bash
# Check for updates to llama.cpp
# Rebuild images if needed
docker compose build --no-cache

# Backup configuration
tar -czf local-ai-gpu-backup-$(date +%Y%m%d).tar.gz \
  docker-compose.yml configs/ scripts/

# Rotate logs if needed
docker compose logs > logs-archive-$(date +%Y%m%d).txt
```

---

## Troubleshooting

### Containers Won't Start

**Check Docker GPU runtime:**
```bash
docker run --rm --gpus all nvidia/cuda:11.8.0-base nvidia-smi
```

**Check logs for errors:**
```bash
docker compose logs gpu-server-1 --tail=100
```

### Model Loading Fails

**Symptoms:**
- 503 errors persist for >2 minutes
- "llama.cpp server failed to start" in logs

**Solutions:**

1. **Check model file exists:**
```bash
ls -lh ~/gpu-server/models/model.gguf
```

2. **Verify model is valid GGUF:**
```bash
file ~/gpu-server/models/model.gguf
# Should say: "data" or show GGUF signature
```

3. **Check VRAM:**
```bash
nvidia-smi
# Make sure you have enough free VRAM
```

4. **Try fewer GPU layers:**
```yaml
# In docker-compose.yml
- N_GPU_LAYERS=20  # Instead of 33
```

### Out of Memory (OOM)

**Symptoms:**
- CUDA out of memory errors
- Container crashes
- Zombie llama-server processes

**Solutions:**

1. **Use smaller quantization:** Q4_K_M → Q4_0
2. **Reduce context size:** `N_CTX=2048` instead of 4096
3. **Reduce batch size:** `N_BATCH=256` instead of 512
4. **Use smaller model:** 8B → 3B parameters

### Performance Issues

**Slow inference:**

1. **Check GPU utilization:**
```bash
nvidia-smi
# Should show high GPU usage during inference
```

2. **Increase GPU layers:**
```yaml
- N_GPU_LAYERS=99  # Offload all layers
```

3. **Check CPU isn't bottleneck:**
```bash
top
# Look for high CPU usage on llama-server
```

4. **Enable mlock (already enabled):**
```bash
# Locks model in RAM to prevent swapping
--mlock
```

### LiteLLM Not Starting

**Check GPU servers are healthy:**
```bash
docker compose ps
# All gpu-server-X should show (healthy)
```

**Check LiteLLM logs:**
```bash
docker compose logs litellm-proxy
```

**Test GPU server directly:**
```bash
curl http://localhost:8080/health
```

---

## Performance Tuning

### For Maximum Throughput

```yaml
environment:
  - N_GPU_LAYERS=99  # All layers on GPU
  - N_CTX=2048       # Smaller context = faster
  - N_BATCH=512      # Larger batches
  - N_THREADS=4      # Match your CPU cores
```

### For Low Latency

```yaml
environment:
  - N_GPU_LAYERS=99  # All layers on GPU
  - N_CTX=4096       # Keep full context
  - N_BATCH=128      # Smaller batches = lower latency
  - N_THREADS=2
```

### For Maximum Quality

```yaml
# Use larger quantization
wget <Q5_K_M_MODEL_URL> -O models/model.gguf

environment:
  - N_GPU_LAYERS=99
  - N_CTX=8192       # Larger context
  - N_BATCH=512
```

### Power Limiting (Multiple GPUs)

For servers with many GPUs to prevent overheating:

```bash
# Install service
sudo cp nvidia-power-limit.service /etc/systemd/system/
sudo nano /etc/systemd/system/nvidia-power-limit.service

# Edit to set power limit for each GPU
# Example: -pl 90 -i 0 (90W limit for GPU 0)

sudo systemctl enable --now nvidia-power-limit.service
sudo systemctl status nvidia-power-limit.service
```

Check power limits:
```bash
nvidia-smi -q -d POWER
```

---

## Quick Reference

### Common Commands

```bash
# Start everything
docker compose up -d

# Stop everything
docker compose down

# Restart GPU servers
docker compose restart gpu-server-{1..8}

# View logs
docker compose logs -f gpu-server-1

# Check status
docker compose ps

# Update code without rebuild
docker compose restart <service>

# Rebuild and restart
docker compose up -d --build

# Clean up
docker system prune -f
```

### Port Reference

| Service | Internal Port | External Port(s) | Purpose |
|---------|--------------|------------------|---------|
| GPU Server 1 | 8080 | 8080 | FastAPI wrapper |
| GPU Server 2-8 | 8080 | 8081-8087 | FastAPI wrappers |
| GPU Servers | 9091 | - | Prometheus metrics |
| LiteLLM Proxy | 4000 | 4000 | Load balancer API |
| Prometheus | 9090 | 9090 | Metrics dashboard |

### File Structure

```
gpu-server/
├── docker-compose.yml          # Main configuration
├── docker-compose.override.yml # Auto-generated volume mounts
├── Dockerfile                   # Container build instructions
├── requirements.txt             # Python dependencies
├── server.py                    # FastAPI wrapper
├── config.py                    # Configuration
├── metrics.py                   # Prometheus metrics
├── routes.py                    # API routes
├── llama_client.py              # llama.cpp client
├── models/
│   └── model.gguf              # Active model (symlink or file)
├── configs/
│   ├── litellm_config.yaml     # LiteLLM configuration
│   └── prometheus.yml          # Prometheus scrape config
└── scripts/
    └── setup.sh                # Setup helper script
```

---

## Support & Resources

- **llama.cpp Documentation**: https://github.com/ggml-org/llama.cpp
- **GGUF Models**: https://huggingface.co/models?library=gguf
- **NVIDIA Docker**: https://github.com/NVIDIA/nvidia-docker
- **LiteLLM Docs**: https://docs.litellm.ai/

For issues with this deployment, check the logs and refer to the Troubleshooting section above.
