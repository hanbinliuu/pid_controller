# Multi-stage build for PID Tuning System
# Use official Python image (works with Docker mirror configuration)
FROM python:3.12-slim AS backend-builder

# Set working directory
WORKDIR /app

# Use Aliyun mirror for faster package downloads in China
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources || true

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements
COPY web_tuning/backend/requirements.txt ./requirements.txt

# Install Python dependencies with Aliyun PyPI mirror
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# Final stage
FROM python:3.12-slim

WORKDIR /app

# Use Aliyun mirror for faster package downloads in China
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources || true

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=backend-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Copy application files
COPY web_tuning/backend/ ./backend/
COPY web_tuning/frontend/ ./frontend/
COPY web_tuning/servers/ ./servers/
COPY web_tuning/scripts/ ./scripts/
COPY web_tuning/data/ ./data/
COPY web_tuning/.env.example ./.env

# Copy core dependencies from parent directory
COPY core/ ./core/

# Create necessary directories
RUN mkdir -p logs data && \
    chmod +x scripts/*.sh backend/*.sh 2>/dev/null || true

# Expose ports
EXPOSE 8000 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["python", "backend/app.py"]
