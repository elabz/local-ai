# LiteLLM Database Configuration

## Summary

LiteLLM is configured with **master key authentication** and does not currently use a database. This is suitable for production-like API access testing as requested.

## Architecture

- **LiteLLM Authentication**: Master key only (`sk-O5z4E7s-6NhLDG3ZZbq9tQ`)
- **Database**: Not configured (PostgreSQL required for API key auth)
- **HeartCode Backend**: Uses separate MySQL database (unchanged)

## Why No Database?

LiteLLM uses **Prisma ORM** for database operations, which only supports:
- PostgreSQL
- MySQL (via Prisma's MySQL driver, but LiteLLM's Prisma setup specifically requires PostgreSQL)
- SQL Server
- SQLite

The HeartCode backend uses **MySQL**, which is incompatible with LiteLLM's Prisma requirements. These cannot share the same database.

## Current Setup (Master Key Auth)

**Advantages:**
- No database configuration needed
- Simpler deployment
- Sufficient for backend API access
- All endpoints functional

**Usage:**
```bash
# All requests require master key header
curl -H "Authorization: Bearer sk-O5z4E7s-6NhLDG3ZZbq9tQ" \
  http://localhost:4000/v1/chat/completions
```

## Future: API Key Authentication (Optional)

If you want per-API-key authentication, rate limiting, and budget tracking through LiteLLM:

### Step 1: Set up PostgreSQL
```bash
# Add to infrastructure/docker/docker-compose.yml
postgres:
  image: postgres:15-alpine
  environment:
    POSTGRES_USER: litellm
    POSTGRES_PASSWORD: secure_password
    POSTGRES_DB: litellm
  ports:
    - "5432:5432"
  volumes:
    - litellm_postgres:/var/lib/postgresql/data

volumes:
  litellm_postgres:
```

### Step 2: Update LiteLLM docker-compose.yml
```yaml
environment:
  - DATABASE_URL=postgresql://litellm:secure_password@host.docker.internal:5432/litellm
```

### Step 3: Restart LiteLLM
```bash
cd infrastructure/litellm-cloud
docker compose down
docker compose up -d
docker compose logs -f litellm
```

LiteLLM will automatically initialize the PostgreSQL schema and enable API key management.

### Step 4: Create API Keys
```bash
# Create an API key via LiteLLM API
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer sk-O5z4E7s-6NhLDG3ZZbq9tQ" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user123", "team_id": "team123"}'
```

## Testing

**Verify LiteLLM is Working:**
```bash
# Health check
curl -H "Authorization: Bearer sk-O5z4E7s-6NhLDG3ZZbq9tQ" \
  http://localhost:4000/health

# Chat endpoint
curl -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-O5z4E7s-6NhLDG3ZZbq9tQ" \
  -H "Content-Type: application/json" \
  -d '{"model": "heartcode-chat-sfw", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 50}'

# Embeddings endpoint
curl -X POST http://localhost:4000/v1/embeddings \
  -H "Authorization: Bearer sk-O5z4E7s-6NhLDG3ZZbq9tQ" \
  -H "Content-Type: application/json" \
  -d '{"model": "heartcode-embed", "input": ["test"]}'
```

## References

- LiteLLM Documentation: https://docs.litellm.ai/
- Prisma Supported Databases: https://www.prisma.io/docs/reference/database-reference/supported-databases
