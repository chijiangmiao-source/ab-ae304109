FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST_ADDR=0.0.0.0 \
    HOST_PORT=8080

WORKDIR /app

# 零第三方依赖：仅复制应用、测试与一次性验收服务。
COPY app/ ./app/
COPY tests/ ./tests/
COPY verify/ ./verify/

RUN chmod +x /app/verify/verify \
    && python -m compileall -q /app/app /app/verify

EXPOSE 8080

CMD ["python", "-m", "app.web.server"]
