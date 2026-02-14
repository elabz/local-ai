# PEA GPU Server Setup Guide

Complete instructions for setting up a GPU inference server from scratch using Pascal-architecture NVIDIA GPUs. This guide covers the PEA server (192.168.0.144) with 8x P104-100 GPUs, but can be adapted for similar hardware.

## Prerequisites

### Hardware Requirements
- **CPU**: x86-64 processor (AVX not required — Celeron/Pentium work fine)
- **RAM**: 32GB minimum (16GB possible with reduced container memory limits)
- **GPUs**: NVIDIA Pascal or newer (compute capability 6.1+), 6-8GB VRAM each
- **Storage**: 50GB+ for models, Docker images, and backends
- **Network**: Gigabit LAN connection to proxy server

### Tested Hardware (PEA)
| Component | Spec |
|-----------|------|
| CPU | Intel Celeron 3865U (2-core, 1.8GHz, no AVX/AVX2) |
| RAM | 32GB DDR4 |
| GPUs | 8x NVIDIA P104-100 (8GB VRAM, GP104, Pascal, compute 6.1) |
| OS | Ubuntu 22.04 LTS |
| Power | 90W limit per GPU |

## Step 1: OS and Driver Setup

### 1.1 Install Ubuntu 22.04 LTS

Standard server installation. Ensure SSH access is configured.

### 1.2 Install NVIDIA Drivers

```bash
# Add NVIDIA driver PPA
sudo add-apt-repository ppa:graphics-drivers/ppa
sudo apt update

# Install driver (535+ recommended for Pascal)
sudo apt install nvidia-driver-535

# Reboot
sudo reboot
```

Verify after reboot:
```bash
nvidia-smi
# Should show all GPUs with driver version and CUDA version
```

### 1.3 Install Docker with NVIDIA Container Toolkit

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install nvidia-container-toolkit

# Configure Docker runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify:
```bash
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### 1.4 GPU Power Limit (Optional but Recommended)

Create a systemd service to set GPU power limits on boot:

```bash
sudo tee /etc/systemd/system/nvidia-power-limit.service << 'EOF'
[Unit]
Description=Set NVIDIA GPU Power Limits
After=nvidia-persistenced.service

[Service]
Type=oneshot
ExecStart=/usr/bin/nvidia-smi -pl 90
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable nvidia-power-limit.service
sudo systemctl start nvidia-power-limit.service
```

## Step 2: Clone Repository

```bash
cd ~
git clone https://github.com/elabz/local-ai.git
cd local-ai/gpu-server
```

## Step 3: Download Models

### 3.1 Automated Download

```bash
./scripts/download-models.sh
# Downloads:
#   - Stheno v3.4 8B Q5_K_M (SFW chat, ~5.7GB)
#   - Josiefied-Qwen3-8B Q5_K_M (NSFW chat, ~5.6GB)
#   - nomic-embed-text-v1.5 Q8_0 (embeddings, ~137MB)

# For lower VRAM GPUs (6GB), use Q4 quantization:
./scripts/download-models.sh --fallback-q4
```

### 3.2 Manual Download (if huggingface-cli unavailable)

```bash
cd models/

# SFW Chat Model
wget "https://huggingface.co/bartowski/Llama-3.1-8B-Stheno-v3.4-GGUF/resolve/main/Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf"

# NSFW Chat Model
wget "https://huggingface.co/Mungert/Josiefied-Qwen3-8B-abliterated-v1-GGUF/resolve/main/Josiefied-Qwen3-8B-abliterated-v1-q5_k_m.gguf"

# Embedding Model
wget "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf"
```

### 3.3 Image Model

The Segmind SSD-1B model auto-downloads from HuggingFace on the first image generation request. No manual download needed.

### 3.4 Verify Models

```bash
ls -lh models/*.gguf
# Expected:
# Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf     ~5.7GB
# Josiefied-Qwen3-8B-abliterated-v1-q5_k_m.gguf  ~5.6GB
# nomic-embed-text-v1.5.Q8_0.gguf           ~137MB
```

## Step 4: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` to set model paths per GPU. The default `.env.example` is pre-configured for the standard layout:

| GPU | Type | Model Path |
|-----|------|------------|
| 1-3 | SFW Chat | `/models/Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf` |
| 4-7 | NSFW Chat | `/models/Josiefied-Qwen3-8B-abliterated-v1-q5_k_m.gguf` |
| 8 | Image | Managed by LocalAI (no path needed) |

Each GPU has three environment variables:
```bash
GPU_N_MODEL_TYPE=sfw|nsfw    # Used for identification
GPU_N_MODEL_PATH=/models/... # Path inside container (models/ is mounted at /models)
GPU_N_MODEL_NAME=...         # HuggingFace repo name (for metadata)
```

## Step 5: Build Docker Image

The Dockerfile builds llama.cpp from source with CUDA support for Pascal GPUs. Special build flags are needed for CPUs without AVX support.

```bash
docker build -t local-ai-llama:latest .
```

**Build time**: ~10-15 minutes on the first build.

### Key Build Flags (for reference)

```cmake
# Pascal GPU (compute 6.1)
-DCMAKE_CUDA_ARCHITECTURES="61"

# Celeron/no-AVX CPU
-DGGML_NATIVE=OFF
-DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_AVX512=OFF
-DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_BMI2=OFF
-DCMAKE_CXX_FLAGS="-march=x86-64 -mno-bmi2"
```

If your CPU supports AVX, you can enable those flags for better CPU-side performance.

## Step 6: Start Services

### 6.1 Automated Setup

```bash
./scripts/setup-pea.sh
# Runs: download models → build image → start services → health checks
```

### 6.2 Manual Start (Staged)

Start services in stages to avoid overwhelming the system:

```bash
# Chat servers first (GPU 1-7)
docker compose up -d gpu-server-1 gpu-server-2 gpu-server-3 \
  gpu-server-4 gpu-server-5 gpu-server-6 gpu-server-7
sleep 30  # Wait for models to load into VRAM

# Embedding servers (GPU 1-7, share GPUs with chat)
docker compose up -d embedding-server-1 embedding-server-2 embedding-server-3 \
  embedding-server-4 embedding-server-5 embedding-server-6 embedding-server-7
sleep 15

# Image server (GPU 8)
docker compose up -d image-server
sleep 30  # First start installs diffusers backend (~3 min)

# Monitoring
docker compose up -d prometheus node-exporter
```

### 6.3 Verify All Services

```bash
docker compose ps
# All containers should show "healthy"
# Expect: 7 chat + 7 embed + 1 image + prometheus + node-exporter = 17 containers
```

## Step 7: Verify Endpoints

### Chat (SFW - GPU 1, port 8080)
```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"test","messages":[{"role":"user","content":"Hello"}],"max_tokens":20}' \
  | python3 -m json.tool
```

### Chat (NSFW - GPU 4, port 8083)
```bash
curl -s http://localhost:8083/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"test","messages":[{"role":"user","content":"Hello"}],"max_tokens":20}' \
  | python3 -m json.tool
```

### Embeddings (GPU 1, port 8090)
```bash
curl -s http://localhost:8090/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"test","input":"Hello world"}' \
  | python3 -m json.tool | head -10
```

### Image Generation (GPU 8, port 5100)
```bash
curl -s http://localhost:5100/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"model":"heartcode-image","prompt":"a sunset over mountains","size":"512x512"}' \
  | python3 -m json.tool
# First request downloads the Segmind SSD-1B model (~2.5GB) and takes several minutes
# Subsequent requests take ~48 seconds for 512x512
```

## Step 8: LiteLLM Proxy Setup (Prod Server)

The LiteLLM proxy runs on a separate server (192.168.0.152) and load-balances requests across GPUs.

### 8.1 On the Prod Server

```bash
cd ~/local-ai/litellm
cp .env.example .env
```

Edit `.env`:
```bash
LITELLM_MASTER_KEY=sk-your-generated-master-key
LITELLM_DB_PASSWORD=your-strong-db-password
```

Generate a secure master key:
```bash
python3 -c "import secrets; print('sk-' + secrets.token_urlsafe(24))"
```

### 8.2 Start LiteLLM

```bash
docker compose up -d
```

### 8.3 Verify

```bash
# Health check
curl http://localhost:4000/health \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# List models
curl http://localhost:4000/v1/models \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

### 8.4 Create API Keys

```bash
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"models": ["heartcode-chat-sfw","heartcode-chat-nsfw","heartcode-embed","heartcode-image"],
       "key_alias": "my-project"}'
```

## Configuration Reference

### GPU Server Parameters (docker-compose.yml)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `N_GPU_LAYERS` | 33 | Layers offloaded to GPU (all for 8B models) |
| `N_CTX` | 16384 | Context window size |
| `N_BATCH` | 128 | Batch size (reduced for 2-core CPU) |
| `N_UBATCH` | 64 | Micro-batch size (optimal for constrained CPUs) |
| `N_THREADS` | 2 | Match physical CPU cores |
| `CACHE_REUSE` | 256 | Prompt cache reuse window |
| `CACHE_TYPE_K` | q8_0 | KV cache key quantization |
| `CACHE_TYPE_V` | q8_0 | KV cache value quantization |
| `EXTRA_ARGS` | `--jinja --reasoning-budget 0` | Enables Jinja chat templates, disables thinking mode |

### Container Memory Limits

| Container Type | mem_limit | memswap_limit |
|----------------|-----------|---------------|
| Chat server | 2048m | 3072m |
| Embedding server | 512m | 768m |
| Image server | 4096m | 6144m |

### Port Layout

| Port Range | Service | GPU |
|------------|---------|-----|
| 8080-8082 | SFW chat | GPU 1-3 |
| 8083-8086 | NSFW chat | GPU 4-7 |
| 8090-8096 | Embeddings | GPU 1-7 |
| 5100 | Image generation | GPU 8 |
| 9091 (internal) | Prometheus metrics per GPU | GPU 1-7 |
| 9099 | Prometheus | - |
| 9100 | Node Exporter | - |

### LiteLLM Router Settings

| Setting | Value | Description |
|---------|-------|-------------|
| `routing_strategy` | least-busy | Load balancing strategy |
| `num_retries` | 2 | Retries on failure |
| `timeout` | 90s | Request timeout |
| `cooldown_time` | 60s | Cooldown after failures |
| `rpm` (SFW) | 35 | Requests per minute across 3 GPUs |
| `rpm` (NSFW) | 45 | Requests per minute across 4 GPUs |

## Model Details

### SFW Chat: Llama-3.1-8B-Stheno-v3.4

- **Architecture**: Llama 3.1 8B
- **Chat template**: Llama3 format (handled natively by llama.cpp)
- **Quantization**: Q5_K_M (~5.7GB)
- **VRAM usage**: ~6.5GB with 16K context
- **HuggingFace**: `bartowski/Llama-3.1-8B-Stheno-v3.4-GGUF`

### NSFW Chat: Josiefied-Qwen3-8B-abliterated-v1

- **Architecture**: Qwen3 8B (abliterated for uncensored output)
- **Chat template**: ChatML (`<|im_start|>`/`<|im_end|>`) — requires `--jinja` flag
- **Thinking mode**: Disabled via `--reasoning-budget 0` (prevents `<think>` blocks)
- **Quantization**: Q5_K_M (~5.6GB)
- **VRAM usage**: ~6.5GB with 16K context
- **HuggingFace**: `Mungert/Josiefied-Qwen3-8B-abliterated-v1-GGUF`

### Embeddings: nomic-embed-text-v1.5

- **Dimensions**: 768
- **Quantization**: Q8_0 (~137MB)
- **Encoding**: Float format
- **HuggingFace**: `nomic-ai/nomic-embed-text-v1.5-GGUF`

### Image: Segmind SSD-1B

- **Architecture**: SDXL distilled (Segmind Stable Diffusion 1B)
- **Backend**: HuggingFace diffusers via LocalAI
- **Precision**: FP16
- **Pipeline**: StableDiffusionXLPipeline
- **Scheduler**: DPM++ 2M Karras
- **Steps**: 20 (config), 50 (diffusers default)
- **Generation time**: ~48 seconds for 512x512
- **VRAM usage**: ~6-7GB during generation
- **HuggingFace**: `segmind/SSD-1B`

## Troubleshooting

### Container keeps restarting
```bash
docker compose logs gpu-server-N --tail 20
# Common causes:
# - "Model not found" → check .env model paths and filename case
# - OOM → reduce N_CTX or increase mem_limit
```

### Chat template issues (garbled output)
Ensure `EXTRA_ARGS: "--jinja --reasoning-budget 0"` is set in docker-compose.yml. The `--jinja` flag tells llama.cpp to use the model's built-in chat template.

### Image generation "backend not found: diffusers"
The diffusers backend installs from LocalAI gallery on first container start. Check that:
1. `BACKENDS_PATH=/backends` is set in environment
2. `image_backends` volume is mounted at `/backends`
3. Container has internet access for the initial download (~7.4GB)

Check install progress:
```bash
docker exec pea-image-1 du -sh /backends/cuda12-diffusers/
```

### GPU not detected
```bash
# Verify NVIDIA runtime
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi

# Check specific GPU
nvidia-smi -i 0  # GPU index 0-7
```

### No AVX CPU errors
If llama.cpp crashes with "Illegal instruction", the Docker image was built with AVX enabled. Rebuild with the flags shown in Step 5.

## Adapting for Different Hardware

### Different GPU Count
Edit `docker-compose.yml`:
- Adjust service definitions (add/remove `gpu-server-N` and `embedding-server-N`)
- Update `NVIDIA_VISIBLE_DEVICES` for each service (0-indexed physical GPU IDs)
- Update `litellm/config.yaml` endpoint list accordingly

### Different GPU Models
- **6GB VRAM (P106-100)**: Use Q4_K_M quantization, reduce N_CTX to 8192
- **8GB VRAM (P104-100)**: Q5_K_M works well, N_CTX up to 16384
- **12GB+ VRAM**: Can use Q8_0 or even FP16 quantization

### CPU with AVX Support
Enable AVX flags in the Dockerfile for better CPU-side performance:
```cmake
-DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON
```
Remove `-march=x86-64` and `-mno-bmi2` overrides.

### Different Models
1. Download the new GGUF model to `models/`
2. Update `.env` with the new model path
3. If the model uses a different chat template, ensure `--jinja` is in `EXTRA_ARGS`
4. Update `litellm/config.yaml` with the new model filename
5. Restart: `docker compose restart gpu-server-N`
