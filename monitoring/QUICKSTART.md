# Monitoring Quick Start

## Start Development Environment

```bash
./start-dev.sh
```

This starts:
- Frontend (React)
- Backend (FastAPI)
- Databases (MySQL, Redis, Qdrant)
- **Grafana** (monitoring dashboards)
- **Alertmanager** (Slack notifications)

## Access Monitoring

**Grafana Dashboards**: http://localhost:3001
- Login: `admin` / `admin`
- Dashboard: **Hardware Monitoring - CPU & GPU**

**Prometheus** (on GPU server): http://192.168.0.145:9090

**Alertmanager**: http://localhost:9093

## Slack Alerts

Alerts are sent to **#hardware-alerts** channel when:
- CPU/GPU temperature exceeds thresholds
- GPU memory usage > 95%
- CPU usage > 90%
- Models go offline

## GPU Server Components (on ash server)

Already running and configured:
- 8x GPU Servers (llama.cpp inference)
- LiteLLM Proxy (load balancing)
- Prometheus (metrics collection)
- Node Exporter (CPU/system metrics)

**Status**: http://192.168.0.145:4000/health

## Configuration Files

- **Alert Rules**: `infrastructure/monitoring/alertmanager/alertmanager.yml`
- **Prometheus Config**: On GPU server at `~/heartcode/gpu-server/configs/prometheus.yml`
- **GPU Server Config**: `gpu-server/config.py`
- **Grafana Dashboards**: `infrastructure/monitoring/grafana/provisioning/dashboards/`

## Troubleshooting

**No metrics in Grafana?**
- Check GPU server Prometheus: http://192.168.0.145:9090
- Verify data source in Grafana settings

**No Slack alerts?**
```bash
# Check Alertmanager
docker logs local-ai-alertmanager

# Test alert
curl -XPOST http://localhost:9093/api/v2/alerts -H "Content-Type: application/json" -d '[{
  "labels": {"alertname": "Test", "severity": "warning"},
  "annotations": {"summary": "Test alert"}
}]'
```

## Stop Development Environment

```bash
./stop-dev.sh
```
