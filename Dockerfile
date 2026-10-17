FROM python:3.12-slim
# The worker (D18) decodes with ffmpeg, checks FLAC with flac, fingerprints with fpcalc and files with beets.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg flac libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir beets==1.6.0 mediafile==0.12.0 confuse==2.0.1   # = the host's working set
WORKDIR /app
COPY subsonic/ subsonic/
COPY crates/ crates/
COPY sourcing/ sourcing/
COPY web/ web/
COPY scripts/ scripts/
COPY deploy/beets.yaml deploy/beets.yaml
COPY deploy/policy.toml deploy/policy.toml
ARG GIT_SHA=dev
LABEL org.opencontainers.image.revision=$GIT_SHA
ENV CRATES_DB=/data/crates.db CRATES_BIND=0.0.0.0 CRATES_PORT=4580
VOLUME ["/data"]
EXPOSE 4580
CMD ["python", "-m", "crates.cli", "serve"]
