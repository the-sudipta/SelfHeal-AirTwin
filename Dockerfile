# syntax=docker/dockerfile:1.7
# SelfHeal-AirTwin image: pinned Python 3.11, Java 17 for Spark, hashed dependencies,
# verified datasets and Spark-Kafka connector JARs baked in, so the container runs offline.

ARG PYTHON_IMAGE=python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60
ARG JAVA_IMAGE=eclipse-temurin:17-jre@sha256:4faa9eaf440514dd4f7ef71fecb92526e13679aea039bed5d2fc98e885c60dee

FROM ${JAVA_IMAGE} AS java

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    OMP_NUM_THREADS=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
# LightGBM needs the OpenMP runtime; it runs single-threaded (OMP_NUM_THREADS=1).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Stage deps: every package and its hash come from requirements.lock.
FROM base AS deps
COPY requirements.lock /tmp/requirements.lock
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes -r /tmp/requirements.lock

# Stage jars: Spark-Kafka connector and its two dependencies missing from PySpark,
# each verified against a pinned SHA-256 (cross-checked with Maven Central's SHA-1).
FROM base AS jars
ADD --chmod=0644 --checksum=sha256:3e458fbf575e8bcdb58f2f3b1a6c51b60e47a75c627f242bc6911fb04de6939b \
    https://repo1.maven.org/maven2/org/apache/spark/spark-sql-kafka-0-10_2.13/4.3.0/spark-sql-kafka-0-10_2.13-4.3.0.jar /opt/spark-jars/
ADD --chmod=0644 --checksum=sha256:e36eeca0a3950518567fa8d744e9948880fdc79a478baadad00e305d145d97c9 \
    https://repo1.maven.org/maven2/org/apache/spark/spark-token-provider-kafka-0-10_2.13/4.3.0/spark-token-provider-kafka-0-10_2.13-4.3.0.jar /opt/spark-jars/
ADD --chmod=0644 --checksum=sha256:014b4ef36884478a932641818b080c36a8f8e2e92dc771e800c9d2694f4f83d8 \
    https://repo1.maven.org/maven2/org/apache/kafka/kafka-clients/3.9.2/kafka-clients-3.9.2.jar /opt/spark-jars/
ADD --chmod=0644 --checksum=sha256:f77a5060d6936a9144023584232f9de3f2248f1abfe156e9d31795f18770674f \
    https://repo1.maven.org/maven2/org/apache/commons/commons-pool2/2.13.1/commons-pool2-2.13.1.jar /opt/spark-jars/

# Stage data: download both datasets and stop the build on any checksum mismatch.
FROM deps AS data
WORKDIR /app
COPY src ./src
COPY configs ./configs
COPY data/checksums.sha256 ./data/checksums.sha256
RUN PYTHONPATH=/app/src /opt/venv/bin/python -m airtwin.cli download

# Final stage: non-root, offline, with Java for Spark.
FROM base AS runtime
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="SelfHeal-AirTwin" \
      org.opencontainers.image.description="Self-healing digital twin for drift detection and correction in low-cost air-quality sensors" \
      org.opencontainers.image.source="https://github.com/the-sudipta/SelfHeal-AirTwin" \
      org.opencontainers.image.url="https://the-sudipta.github.io/SelfHeal-AirTwin/" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Sudipta Kumar Das"
ENV JAVA_HOME=/opt/java/openjdk \
    PATH="/opt/venv/bin:/opt/java/openjdk/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PYSPARK_PYTHON=/opt/venv/bin/python \
    AIRTWIN_CONFIG=/app/configs/default.yaml
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=deps /opt/venv /opt/venv
COPY --from=jars /opt/spark-jars /opt/spark-jars
RUN useradd --create-home --uid 10001 airtwin
WORKDIR /app
COPY --from=data /app/data/raw ./data/raw
COPY data/checksums.sha256 data/README.md ./data/
COPY configs ./configs
COPY src ./src
COPY README.md LICENSE CITATION.cff pyproject.toml ./
RUN mkdir -p /app/results /app/data/processed \
 && chown -R airtwin:airtwin /app/results /app/data/processed
USER airtwin
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=30s --start-period=20s --retries=3 \
    CMD ["python", "-m", "airtwin.cli", "check"]
ENTRYPOINT ["python", "-m", "airtwin.cli"]
CMD ["replay"]
