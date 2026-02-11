# HeartCode LiteLLM Proxy

This directory contains all LiteLLM configuration and orchestration for HeartCode. It supports both local development (connecting to GPU servers) and cloud deployment (with SSH tunnels).

## Overview

| Scenario | Config File | Network | Use Case |
|----------|-------------|---------|----------|
| **Local Development** | `config-local.yaml` | LAN to 192.168.0.145 (ASH hardware) | Testing with remote GPU servers |
| **Cloud Deployment** | `config.yaml` | SSH tunnels | Public API gateway with custom auth |

## Local Development Setup

### Quick Start

For local development with GPU servers on remote hardware (192.168.0.145):

```bash
# 1. Ensure backend is running (from infrastructure/docker directory)
cd infrastructure/docker
docker compose up -d  # Starts MySQL, Redis, backend, frontend, etc.

# 2. Start LiteLLM (from infrastructure/litellm-cloud directory)
cd ../litellm-cloud
docker compose up -d

# 3. Verify LiteLLM is running
curl http://localhost:4000/health

# 4. Test chat endpoint (use your LITELLM_MASTER_KEY from .env)
curl http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "heartcode-chat-sfw",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 100
    }'
```

**Requirements**:
- GPU servers running on remote hardware at `192.168.0.145` (ASH infrastructure)
- MySQL database running locally (in infrastructure/docker stack)
- Backend running locally at `http://localhost:8000`
- Network access to 192.168.0.145 on ports 8080-8087 (GPU servers) and 8090-8097 (embedding servers)

### Local Configuration

**File**: `config-local.yaml`
- Connects to GPU servers via LAN IP: `http://192.168.0.145:8080-8087`
- Connects to embedding servers via LAN IP: `http://192.168.0.145:8090-8097`
- Uses master key authentication (no custom auth needed for local)
- Models: `heartcode-chat-sfw` (GPUs 1-4), `heartcode-chat-nsfw` (GPUs 5-8), `heartcode-embed` (embeddings)
- Database: Connects to local MySQL at `host.docker.internal:3306`

**View logs**:
```bash
docker compose logs -f litellm
```

**Stop LiteLLM**:
```bash
docker compose down
```

**Troubleshooting Network Issues**:
- Cannot connect to 192.168.0.145? Check VPN/network access to ASH hardware
- GPU server unreachable? Verify ports 8080-8087 are open and GPU servers are running
- Database connection error? Ensure MySQL is running in infrastructure/docker stack

---

## Cloud Deployment Architecture

```
Internet
    │
    ▼
┌─────────────────────────────────────┐
│  Cloud Server                       │
│  ┌─────────────────────────────┐    │
│  │  LiteLLM Proxy (:4000)      │    │
│  │  - Custom auth              │    │
│  │  - Rate limiting            │    │
│  │  - Load balancing           │    │
│  └──────────┬──────────────────┘    │
│             │                        │
│  SSH Tunnels (reverse)               │
│    :8000 → Backend                   │
│    :8080-8087 → GPU Servers          │
└─────────────┼───────────────────────┘
              │
    SSH Tunnel│
              │
┌─────────────▼───────────────────────┐
│  On-Prem Network                    │
│                                     │
│  ┌─────────────┐  ┌──────────────┐  │
│  │  Backend    │  │  Frontend    │  │
│  │  (:8000)    │  │  (:3000)     │  │
│  └─────────────┘  └──────────────┘  │
│                                     │
│  ┌─────────────────────────────┐    │
│  │  GPU Servers (8x)           │    │
│  │  :8080 - GPUs 1-8           │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
```

## Setup Instructions

### 1. SSH Tunnel Setup (On-Prem Server)

Create persistent SSH tunnels from on-prem to cloud using autossh:

```bash
# Install autossh
sudo apt install autossh

# Create tunnel service file
sudo tee /etc/systemd/system/local-ai-tunnel.service << 'EOF'
[Unit]
Description=HeartCode SSH Tunnels to Cloud
After=network.target

[Service]
Type=simple
User=heartcode
ExecStart=/usr/bin/autossh -M 0 -N \
    -o "ServerAliveInterval 30" \
    -o "ServerAliveCountMax 3" \
    -o "ExitOnForwardFailure yes" \
    -R 8000:localhost:8000 \
    -R 8080:gpu-server-1:8080 \
    -R 8081:gpu-server-2:8080 \
    -R 8082:gpu-server-3:8080 \
    -R 8083:gpu-server-4:8080 \
    -R 8084:gpu-server-5:8080 \
    -R 8085:gpu-server-6:8080 \
    -R 8086:gpu-server-7:8080 \
    -R 8087:gpu-server-8:8080 \
    cloud-user@cloud-server.example.com
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl enable local-ai-tunnel
sudo systemctl start local-ai-tunnel
```

### 2. Cloud Server Setup

```bash
# Clone the repo (or copy these files)
cd /opt/heartcode
mkdir -p litellm-cloud
cd litellm-cloud

# Copy config files
# - config.yaml
# - custom_auth.py
# - docker-compose.yml

# Create .env file
cat > .env << 'EOF'
HEARTCODE_BACKEND_URL=http://host.docker.internal:8000
HEARTCODE_BACKEND_TIMEOUT=10.0
EOF

# Start LiteLLM
docker compose up -d

# Check logs
docker compose logs -f
```

### 3. Verify Setup

```bash
# Health check
curl http://localhost:4000/health

# Test with API key (get from HeartCode web UI)
curl http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer hc-sk-your-api-key" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "heartcode-chat-sfw",
        "messages": [{"role": "user", "content": "Hello!"}]
    }'
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HEARTCODE_BACKEND_URL` | `http://host.docker.internal:8000` | Backend URL via SSH tunnel |
| `HEARTCODE_BACKEND_TIMEOUT` | `10.0` | Auth request timeout (seconds) |
| `LANGFUSE_PUBLIC_KEY` | - | Optional: Langfuse observability |
| `LANGFUSE_SECRET_KEY` | - | Optional: Langfuse observability |
| `LANGFUSE_HOST` | - | Optional: Langfuse host URL |

### Model Mapping

| Public API Model | Internal Model | Description |
|------------------|----------------|-------------|
| `heartcode-default` | `heartcode-chat-sfw` | Default SFW model |
| `heartcode-sfw` | `heartcode-chat-sfw` | Explicit SFW model |
| `heartcode-nsfw` | `heartcode-chat-nsfw` | NSFW (age-verified only) |

### Rate Limits

Rate limits are set per API key based on subscription tier:

| Tier | RPM | TPM | Daily Tokens |
|------|-----|-----|--------------|
| Free | 10 | 1,000 | 10,000 |
| Premium | 60 | 7,000 | 100,000 |
| Admin | 1,000 | 70,000 | 10,000,000 |

## HTTPS Setup (Optional)

To enable HTTPS with nginx:

1. Place SSL certificates in `./certs/`:
   - `server.crt` - Certificate
   - `server.key` - Private key

2. Create `nginx.conf`:
```nginx
events {
    worker_connections 1024;
}

http {
    upstream litellm {
        server litellm:4000;
    }

    server {
        listen 80;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl;

        ssl_certificate /etc/nginx/certs/server.crt;
        ssl_certificate_key /etc/nginx/certs/server.key;

        location / {
            proxy_pass http://litellm;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_buffering off;
        }
    }
}
```

3. Start with HTTPS profile:
```bash
docker compose --profile https up -d
```

## Troubleshooting

### SSH Tunnel Issues

```bash
# Check tunnel status
sudo systemctl status local-ai-tunnel

# Test tunnel connectivity
curl http://localhost:8000/api/v1/health  # Backend
curl http://localhost:8080/health          # GPU server 1

# View tunnel logs
journalctl -u local-ai-tunnel -f
```

### LiteLLM Issues

```bash
# View logs
docker compose logs -f litellm

# Check health
curl http://localhost:4000/health

# Test auth
curl -v http://localhost:4000/v1/models \
    -H "Authorization: Bearer hc-sk-test"
```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `auth_unavailable` | Backend not reachable | Check SSH tunnel to :8000 |
| `auth_timeout` | Backend slow | Increase `HEARTCODE_BACKEND_TIMEOUT` |
| `model_unavailable` | GPU not reachable | Check SSH tunnels to :8080-8087 |
| `invalid_api_key` | Wrong key format | Key must start with `hc-sk-` |
