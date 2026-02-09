# HeartCode GPU Image Server

AI avatar generation server using LocalAI with Stable Diffusion models.

## Hardware Requirements

- **GPU**: 2x NVIDIA RTX 3070 (or equivalent with 8GB+ VRAM)
- **RAM**: 16GB minimum recommended
- **Storage**: 20GB+ for models
- **NVIDIA Driver**: 525+ (CUDA 12 compatible)

## Architecture

```
                 ┌─────────────────┐
                 │  NGINX Proxy    │
                 │   Port 5100     │
                 └────────┬────────┘
                          │
          ┌───────────────┴───────────────┐
          │                               │
┌─────────▼─────────┐       ┌─────────────▼─────────┐
│   LocalAI #1      │       │      LocalAI #2       │
│   GPU 0 (3070)    │       │      GPU 1 (3070)     │
│   Port 5000       │       │      Port 5001        │
└───────────────────┘       └───────────────────────┘
```

## API Endpoints

LocalAI provides OpenAI-compatible endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/images/generations` | POST | Generate image from prompt |
| `/readyz` | GET | Health check |
| `/models` | GET | List available models |

### Generate Image Request

```bash
curl -X POST http://localhost:5100/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "anime style portrait, beautiful character, detailed face, high quality",
    "model": "avatar-sdxl",
    "size": "512x512",
    "n": 1
  }'
```

### Response Format

```json
{
  "created": 1704067200,
  "data": [
    {
      "url": "http://localhost:5100/generated/abc123.png",
      "b64_json": "iVBORw0KGgo..."
    }
  ]
}
```

## Quick Start

### 1. Prerequisites

Install NVIDIA Container Toolkit:

```bash
# Add repository
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# Install
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### 2. Configuration

```bash
# Copy environment file
cp .env.example .env

# Edit settings as needed
nano .env
```

### 3. Start Services

```bash
# Start all services
docker compose up -d

# Watch logs
docker compose logs -f

# Check health
curl http://localhost:5100/health
```

### 4. Download Models

Models are downloaded automatically on first request. First generation will be slow (~2-5 minutes) as models are cached.

To pre-download models:

```bash
# SDXL (recommended for quality)
docker exec local-ai-image-1 curl -X POST http://localhost:8080/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "model": "avatar-sdxl", "size": "512x512"}'
```

## Model Options

### SDXL (Default)

- **Quality**: Best
- **Speed**: ~30-60 seconds @ 512x512
- **VRAM**: ~7GB
- **Config**: `configs/avatar-sdxl.yaml`

### SD 1.5 (Counterfeit V2.5)

- **Quality**: Good (anime-optimized)
- **Speed**: ~10-20 seconds @ 512x512
- **VRAM**: ~4GB
- **Config**: `configs/avatar-sd15.yaml`

## Memory Optimization

For 8GB GPUs, the configs include:

- FP16 precision
- VAE slicing and tiling
- CPU offloading when idle

If you encounter OOM errors:

1. Reduce batch size
2. Use SD 1.5 instead of SDXL
3. Generate at 512x512 instead of 1024x1024

## Monitoring

Check GPU usage:

```bash
watch -n 1 nvidia-smi
```

Check container logs:

```bash
docker compose logs -f image-server-1
docker compose logs -f image-server-2
```

## HeartCode Integration

The backend connects to this server via the `IMAGE_API_URL` environment variable.

In HeartCode backend `.env`:

```
IMAGE_API_URL=http://192.168.x.x:5100/v1
```

## Troubleshooting

### Model won't load

- Check VRAM with `nvidia-smi`
- Try SD 1.5 if SDXL fails
- Increase container memory limits

### Slow generation

- First request downloads models (~10GB for SDXL)
- Subsequent requests are much faster
- Consider SSD for model storage

### CUDA errors

- Update NVIDIA driver to 525+
- Reinstall nvidia-container-toolkit
- Check `docker info | grep -i nvidia`
