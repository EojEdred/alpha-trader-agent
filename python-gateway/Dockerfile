FROM python:3.11-slim as builder

WORKDIR /usr/src/a2rchitech

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY services/python-gateway/requirements.txt .
RUN pip install --user -r requirements.txt

# Copy the Python gateway service
COPY services/python-gateway/ .

# Production stage
FROM python:3.11-slim

WORKDIR /usr/src/a2rchitech

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local

# Copy the Python gateway service
COPY services/python-gateway/ .

# Create a non-root user
RUN useradd --create-home --shell /bin/bash --uid 1001 a2rchitech && \
    chown -R a2rchitech:a2rchitech /usr/src/a2rchitech

USER a2rchitech

EXPOSE 8000

ENV PATH=/root/.local/bin:$PATH

CMD ["python", "-m", "app.main"]