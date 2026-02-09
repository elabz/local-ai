# Hardware Monitoring & Alerts

## Quick Access

**Grafana Dashboard**: http://localhost:3001
- Username: `admin`
- Password: `admin`

**Prometheus**: http://192.168.0.145:9090

**Dashboards Available**:
1. **Hardware Monitoring - CPU & GPU** (NEW!) - Real-time hardware health
2. **GPU Servers Monitoring** - Inference performance metrics

## Alert Thresholds

### 🔴 CRITICAL Alerts (Immediate Action Required)
- **CPU Temperature > 85°C** - Fires after 1 minute
- **GPU Temperature > 85°C** - Fires after 1 minute

### 🟡 WARNING Alerts
- **CPU Temperature > 70°C** - Fires after 2 minutes
- **GPU Temperature > 80°C** - Fires after 2 minutes
- **GPU Memory > 95%** - Fires after 5 minutes
- **CPU Usage > 90%** - Fires after 5 minutes
- **Model Offline** - Fires after 2 minutes
- **Inference Latency > 30s** - Fires after 5 minutes

## Current Hardware Status

**CPU Temperatures** (as of setup):
- Core temps: ~23-28°C ✅ Healthy
- Package temp: ~25°C ✅ Healthy

**GPU Temperatures**:
- All GPUs: Check dashboard for real-time data

## Key Metrics

### CPU Metrics
```promql
# CPU Temperature (max across all cores)
max(node_hwmon_temp_celsius{chip=~"platform_coretemp.*"})

# CPU Usage %
100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Individual core temperatures
node_hwmon_temp_celsius{chip=~"platform_coretemp.*"}
```

### GPU Metrics
```promql
# GPU Temperature (all GPUs)
gpu_temperature_celsius

# GPU Temperature (max)
max(gpu_temperature_celsius)

# GPU Utilization
gpu_utilization_percent

# GPU Memory Usage %
gpu_memory_used_bytes / gpu_memory_total_bytes * 100
```

### Inference Metrics (Fixed Queries)
```promql
# Requests per second (need data first)
rate(inference_requests_total{status="success"}[5m])

# Average response time (need data first)
rate(inference_duration_seconds_sum[5m]) / rate(inference_duration_seconds_count[5m])

# Tokens per second (need data first)
sum(rate(inference_tokens_total[5m]))
```

**Note**: The inference metrics queries require some chat requests to generate data. The rate() function needs at least 2 data points.

## Viewing Alerts

### In Grafana
1. Go to **Alerting** → **Alert rules**
2. Or check the "Active Alerts" panel at the bottom of the Hardware Monitoring dashboard

### In Prometheus
http://192.168.0.145:9090/alerts

## Emergency Actions

### If CPU/GPU Temperature is CRITICAL:

1. **Check current load**:
   ```bash
   ssh ash "docker stats --no-stream"
   ```

2. **Reduce GPU load** (emergency):
   ```bash
   # Stop some GPU servers temporarily
   ssh ash "cd ~/heartcode/gpu-server && docker compose stop gpu-server-5 gpu-server-6 gpu-server-7 gpu-server-8"
   ```

3. **Check cooling**:
   - Ensure fans are running
   - Check for dust buildup
   - Verify ambient temperature

4. **Monitor in real-time**:
   - Watch Grafana dashboard
   - Check alert status

## Monitoring Best Practices

1. **Regular Checks**: Glance at Grafana dashboard daily
2. **Alert Response**: Investigate any alert within 5 minutes
3. **Temperature Baselines**:
   - Idle CPU: ~25-35°C
   - Idle GPU: ~30-40°C
   - Under load CPU: ~50-70°C (OK), >85°C (CRITICAL)
   - Under load GPU: ~60-80°C (OK), >85°C (CRITICAL)

4. **Preventive Maintenance**:
   - Clean dust filters monthly
   - Monitor ambient room temperature
   - Ensure adequate airflow around server

## Troubleshooting

### Alerts not firing
```bash
# Check if Prometheus is scraping metrics
curl "http://192.168.0.145:9090/api/v1/targets"

# Check alert rules are loaded
curl "http://192.168.0.145:9090/api/v1/rules"
```

### No CPU temperature data
```bash
# Check node-exporter is running
ssh ash "docker ps | grep node-exporter"

# Check metrics endpoint
curl "http://192.168.0.145:9100/metrics" | grep temp
```

### Dashboard not showing data
- Wait 15-30 seconds for first scrape
- Check Prometheus data source in Grafana settings
- Verify GPU servers are running

## Files Modified

- `/heartcode/gpu-server/docker-compose.yml` - Added node-exporter
- `/heartcode/gpu-server/configs/prometheus.yml` - Added node-exporter scrape config
- `/heartcode/gpu-server/configs/alert_rules.yml` - Alert definitions
- `/heartcode/infrastructure/monitoring/grafana/provisioning/dashboards/hardware-monitoring.json` - Dashboard
