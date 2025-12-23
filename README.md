# Odoo 18 LLM Integration Framework

Nền tảng Odoo 18 tích hợp AI/LLM (Large Language Model) toàn diện, biến Odoo thành hệ thống doanh nghiệp thông minh với trợ lý AI.

**Author**: Phạm Quang Hưng
**Website**: https://github.com/hungpq-ai/odoo

---

## Tính năng chính

- **Multi-Provider LLM**: Hỗ trợ OpenAI, Anthropic, Mistral, Replicate
- **AI Chat**: Chat AI real-time tích hợp trong Odoo
- **RAG (Retrieval-Augmented Generation)**: Tìm kiếm ngữ nghĩa trên tài liệu
- **Tool Framework**: AI có thể thực thi các thao tác trong Odoo
- **Knowledge Base**: Xử lý PDF, Word, Excel, PowerPoint, web pages
- **OCR Support**: Nhận dạng văn bản từ ảnh/tài liệu scan
- **MCP Protocol**: Kết nối với Claude Desktop, VS Code, Cursor
- **Agent-to-Agent**: Giao tiếp giữa các AI agent
- **Analytics**: Theo dõi sử dụng, chi phí, hiệu suất AI

---

## Tech Stack

| Thành phần | Công nghệ |
|------------|-----------|
| Platform | Odoo 18.0, Python 3 |
| Database | PostgreSQL 16 + pgvector |
| Vector DB | pgvector, Qdrant, Chroma |
| Container | Docker, Docker Compose |
| LLM Providers | OpenAI, Anthropic, Mistral, Replicate |
| OCR | Tesseract OCR |

---

## Cấu trúc dự án

```
odoo/
├── Dockerfile                    # Custom Odoo 18 + Tesseract OCR
├── docker-compose.yml            # Multi-service orchestration
├── config/
│   └── odoo.conf                 # Cấu hình Odoo
├── addons/                       # Các module LLM
│   ├── llm/                      # Base LLM integration
│   ├── llm_thread/               # AI Chat interface
│   ├── llm_assistant/            # Assistant templates
│   ├── llm_knowledge/            # RAG system
│   ├── llm_generate/             # Content generation
│   ├── llm_tool/                 # Tool framework
│   ├── llm_store/                # Vector store abstraction
│   ├── llm_pgvector/             # PostgreSQL vector
│   ├── llm_qdrant/               # Qdrant integration
│   ├── llm_openai/               # OpenAI provider
│   ├── llm_mistral/              # Mistral provider
│   ├── llm_replicate/            # Replicate provider
│   ├── llm_mcp_server/           # MCP server
│   ├── llm_mcp/                  # MCP client
│   ├── llm_a2a/                  # Agent-to-Agent
│   ├── llm_analytics/            # Usage analytics
│   └── ...                       # 24+ modules
└── knowledge/                    # OCA document modules
```

---

## Yêu cầu hệ thống

- Docker và Docker Compose
- RAM: 4GB+ (khuyến nghị 8GB+)
- Disk: 10GB+
- Port: 8069, 8072, 6333, 6334

---

## Cài đặt

### 1. Clone dự án

```bash
git clone https://github.com/hungpq-ai/odoo.git
```

### 2. Build và khởi chạy

```bash
docker-compose build
docker-compose up -d
```

### 3. Kiểm tra services

| Service | URL | Mô tả |
|---------|-----|-------|
| Odoo Web | http://localhost:8069 | Giao diện chính |
| Odoo Chat | http://localhost:8072 | Real-time chat |
| Qdrant | http://localhost:6333 | Vector DB API |

### 4. Thiết lập lần đầu

1. Truy cập http://localhost:8069
2. Tạo database mới
3. Cài đặt các module LLM cần thiết

---

## Cấu hình

### Environment Variables

```env
HOST=db
USER=odoo
PASSWORD=odoo
POSTGRES_DB=postgres
POSTGRES_PASSWORD=odoo
POSTGRES_USER=odoo
```

### Connection URIs

```
# PostgreSQL/pgvector
postgresql://odoo:odoo@db:5432/postgres

# Qdrant
http://qdrant:6333
```

### Odoo Config (`config/odoo.conf`)

```ini
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons
admin_passwd = admin
db_host = db
db_port = 5432
db_user = odoo
db_password = odoo
limit_time_cpu = 600
limit_time_real = 600
```

---

## Cài đặt Modules

### Modules cơ bản (theo thứ tự)

1. `llm` - Base LLM integration
2. `llm_thread` - AI Chat
3. `llm_tool` - Tool framework
4. `llm_store` - Vector store abstraction

### Modules AI Features

5. `llm_assistant` - Custom assistants
6. `llm_knowledge` - RAG/document search
7. `llm_pgvector` hoặc `llm_qdrant` - Vector DB
8. `llm_tool_knowledge` - RAG tools

### Modules Provider (chọn ít nhất 1)

- `llm_openai` - GPT-4, GPT-3.5
- `llm_replicate` - Various models

### Modules nâng cao

- `llm_analytics` - Usage tracking
- `llm_mcp_server` - Claude Desktop integration
- `llm_document_generator` - Document creation
- `llm_a2a` - Multi-agent orchestration

---

## Cấu hình LLM Provider

1. Vào **Settings → LLM → Providers**
2. Thêm provider (OpenAI, Gemini)
3. Nhập API keys
4. Click **"Fetch Models"** để lấy danh sách models

### Cấu hình Vector Store

1. Vào **LLM → Vector Stores → Create**
2. Chọn Type: pgvector hoặc Qdrant
3. Với Qdrant: URL = `http://qdrant:6333`

### Import Documents (Knowledge Base)

1. Vào **LLM → Knowledge → Upload**
2. Hỗ trợ: PDF, Word, Excel, PowerPoint, Web pages
3. Tài liệu tự động được chunked và embedded

---

## Docker Services

| Container | Image | Port |
|-----------|-------|------|
| odoo18_web | Custom Odoo 18 | 8069, 8072 |
| odoo18_db | pgvector/pgvector:pg16 | 5432 (internal) |
| odoo18_qdrant | qdrant/qdrant:latest | 6333, 6334 |

---

## Commands hữu ích

```bash
# Khởi động
docker-compose up -d

# Dừng
docker-compose down

# Xem logs
docker-compose logs -f odoo18_web

# Restart Odoo
docker-compose restart odoo18_web

# Rebuild
docker-compose build --no-cache
docker-compose up -d
```

---

## Python Dependencies

Các thư viện chính:

- `openai` - OpenAI API
- `qdrant-client` - Qdrant vector DB
- `pgvector`, `numpy` - Vector operations
- `mcp` - Model Context Protocol
- `PyMuPDF`, `python-docx` - Document parsing
- `pytesseract`, `Pillow` - OCR support

---

## Lưu ý Production

- Sử dụng managed PostgreSQL với pgvector
- Sử dụng Qdrant Cloud hoặc self-hosted
- Sử dụng external LLM APIs (OpenAI, Anthropic)
- Monitor usage với LLM Analytics
- Backup PostgreSQL định kỳ
- Sử dụng environment variables cho API keys

---

## Tài liệu bổ sung

- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Hướng dẫn cài đặt chi tiết
- [SETUP_GUIDE.pdf](SETUP_GUIDE.pdf) - Hướng dẫn PDF

---

© 2025-2026 Hung Pham Quang
