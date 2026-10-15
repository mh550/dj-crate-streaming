FROM python:3.12-slim
WORKDIR /app
COPY subsonic/ subsonic/
COPY crates/ crates/
COPY sourcing/ sourcing/
COPY web/ web/
COPY scripts/ scripts/
ENV CRATES_DB=/data/crates.db CRATES_BIND=0.0.0.0 CRATES_PORT=4580
VOLUME ["/data"]
EXPOSE 4580
CMD ["python", "-m", "crates.cli", "serve"]
