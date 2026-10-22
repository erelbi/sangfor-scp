# scp-health ve sangfor_scp kütüphanesi için container imajı (paket PyPI'den kurulur).
#
#   docker run --rm --env-file .env ghcr.io/erelbi/sangfor-scp
#   docker run --rm --env-file .env -v "$PWD/out:/data" ghcr.io/erelbi/sangfor-scp --csv /data
#   docker run --rm --env-file .env --entrypoint python ghcr.io/erelbi/sangfor-scp -c 'import sangfor_scp'
#
# Kimlik bilgileri ortam değişkenleriyle verilir (SCP_HOST, SCP_ACCESS_KEY/SCP_SECRET_KEY
# veya SCP_USERNAME/SCP_PASSWORD); imajın içinde hiçbir değer yoktur.
#
#   docker build --build-arg VERSION=0.4.4 -t sangfor-scp .
FROM docker.io/library/python:3.13-slim
ARG VERSION
RUN test -n "$VERSION" || { echo "VERSION build-arg gerekli" >&2; exit 1; }
LABEL org.opencontainers.image.title="sangfor-scp" \
      org.opencontainers.image.description="Python client for the Sangfor Cloud Platform (SCP) Open-API, with the scp-health report" \
      org.opencontainers.image.source="https://github.com/erelbi/sangfor-scp" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
RUN pip install --no-cache-dir --root-user-action=ignore "sangfor-scp[token-auth]==${VERSION}" \
    && useradd --create-home --uid 10001 scp \
    && mkdir /data && chown scp /data
USER scp
WORKDIR /data
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["scp-health"]
CMD ["--help"]
