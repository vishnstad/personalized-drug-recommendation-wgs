# API + web UI image. Contains the full Layer 1 toolchain (bcftools, Java 17, PharmCAT), so genotype
# calling runs inside the container -- no WSL needed. Build context is the repo root:
#   docker compose build backend
FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends bcftools tabix openjdk-17-jre-headless curl \
 && rm -rf /var/lib/apt/lists/*

ARG PHARMCAT_VERSION=3.4.0
RUN mkdir -p /opt/pharmcat \
 && base=https://github.com/PharmGKB/PharmCAT/releases/download/v${PHARMCAT_VERSION} \
 && curl -fsSL -o /opt/pharmcat/pharmcat-${PHARMCAT_VERSION}-all.jar          ${base}/pharmcat-${PHARMCAT_VERSION}-all.jar \
 && curl -fsSL -o /opt/pharmcat/pharmcat_positions_${PHARMCAT_VERSION}.vcf.bgz ${base}/pharmcat_positions_${PHARMCAT_VERSION}.vcf.bgz \
 && curl -fsSL -o /opt/pharmcat/pharmcat_positions_${PHARMCAT_VERSION}.vcf.bgz.csi ${base}/pharmcat_positions_${PHARMCAT_VERSION}.vcf.bgz.csi

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# code only; data/ (VCFs, per-sample outputs) is mounted as a volume
COPY genomic/ genomic/
COPY retrieval/ retrieval/
COPY llm/ llm/
COPY explainability/ explainability/
COPY backend/ backend/
COPY frontend/ frontend/

ENV BCFTOOLS_BIN=bcftools \
    JAVA_BIN=java \
    PHARMCAT_JAR=/opt/pharmcat/pharmcat-${PHARMCAT_VERSION}-all.jar \
    PYTHONUNBUFFERED=1

EXPOSE 8010
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD curl -fs localhost:8010/api/health || exit 1
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8010", "--log-level", "info"]
