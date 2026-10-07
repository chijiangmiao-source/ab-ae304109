FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

# 零第三方依赖：仅复制应用代码、测试与验收脚本
COPY app/ ./app/
COPY tests/ ./tests/
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/verify

HEALTHCHECK --interval=3s --timeout=3s --start-period=2s --retries=15 \
  CMD python -c "import urllib.request,sys; \
r=urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2); \
sys.exit(0 if r.status==200 else 1)"

EXPOSE 8080

CMD ["python", "-m", "app.server"]
