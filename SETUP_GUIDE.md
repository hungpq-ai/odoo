# Hướng dẫn Setup Odoo 18 + PgVector + Qdrant

## Yêu cầu

- Docker & Docker Compose đã cài đặt

---

## 1. Docker Compose

Thêm các services sau vào file `docker-compose.yml`:

### PgVector (PostgreSQL + Vector Extension)

```yaml
db:
  image: pgvector/pgvector:pg16
  container_name: odoo18_db
  environment:
    - POSTGRES_DB=postgres
    - POSTGRES_PASSWORD=odoo
    - POSTGRES_USER=odoo
  volumes:
    - odoo18-db-data:/var/lib/postgresql/data
  restart: always
```

### Qdrant (Vector Database)

```yaml
qdrant:
  image: qdrant/qdrant:latest
  container_name: odoo18_qdrant
  ports:
    - "6333:6333"  # HTTP API
    - "6334:6334"  # gRPC
  volumes:
    - qdrant-data:/qdrant/storage
  restart: always
```

### Volumes

```yaml
volumes:
  odoo18-db-data:
  qdrant-data:
```

---

## 4. Cấu hình Vector Store trong Odoo

### PgVector (dùng luôn database Odoo)

> Vào **LLM → Vector Stores → Create**
> Type: `pgvector`

### Qdrant

> Vào **LLM → Vector Stores → Create**
> Type: `qdrant`
> URL: `http://qdrant:6333` (trong Docker network)

---

## 5. URI kết nối

### PgVector (PostgreSQL)

| Trường hợp | URI |
|:-----------|:----|
| Trong Odoo (cấu hình module) | `postgresql://odoo:odoo@db:5432/postgres` |
| Từ bên ngoài server | `postgresql://odoo:odoo@<SERVER_IP>:5432/postgres` |

### Qdrant

| Trường hợp | URI |
|:-----------|:----|
| Trong Odoo (cấu hình module) | `http://qdrant:6333` |
| Từ bên ngoài server | `http://<SERVER_IP>:6333` |
| gRPC trong Odoo | `http://qdrant:6334` |
| gRPC từ bên ngoài | `http://<SERVER_IP>:6334` |

### Ví dụ

Nếu server IP là `192.168.1.100`:

| Service | URI |
|:--------|:----|
| Qdrant từ bên ngoài | `http://192.168.1.100:6333` |
| PostgreSQL từ bên ngoài | `postgresql://odoo:odoo@192.168.1.100:5432/postgres` |

---

## 6. Ports tóm tắt

| Service | Port | Mô tả |
|:--------|:-----|:------|
| Qdrant HTTP | `6333` | Vector DB API |
| Qdrant gRPC | `6334` | Vector DB gRPC |
| PostgreSQL | `internal` | Database (không expose ra ngoài) |

---
