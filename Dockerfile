# ============================================================
# geodatalab - GIS Data Laboratory
# Multi-stage build: compile in builder, runtime-only in final
#
# Profiles (ARG PROFILE):
#   kitchen   - Python GIS stack + JupyterLab + whitebox
#   lab       - kitchen + netCDF4/h5py + GRASS GIS + SAGA GIS  [default]
#   institute - lab + R + Julia
#   r+julia   - JupyterLab + R + Julia only (no heavy GIS Python stack)
# ============================================================

# --- Stage 1: Builder ---
FROM debian:trixie-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        python3-setuptools \
        python3-wheel \
        libgdal-dev \
        libproj-dev \
        libgeos-dev \
        libspatialindex-dev \
        libhdf5-dev \
        pkg-config \
        curl \
    && rm -rf /var/lib/apt/lists/*

ARG PROFILE=lab
COPY requirements/ /tmp/requirements/
RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r "/tmp/requirements/${PROFILE}.txt"

# Install latest stable Julia via official installer (juliaup).
# Staged under /opt/juliaup + /opt/julia-depot for the final stage.
RUN mkdir -p /opt/juliaup /opt/julia-depot && \
    case "$PROFILE" in \
        institute|r+julia) \
            curl -fsSL https://install.julialang.org | sh -s -- --yes \
            && cp -a /root/.juliaup/. /opt/juliaup/ \
            && cp -a /root/.julia/juliaup/. /opt/julia-depot/ \
            ;; \
    esac

# --- Stage 2: Runtime ---
FROM debian:trixie-slim

LABEL org.opencontainers.image.title="geodatalab" \
      org.opencontainers.image.description="GIS Data Laboratory" \
      org.opencontainers.image.version="3.0"

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/venv/bin:/usr/local/bin:$PATH \
    VIRTUAL_ENV=/venv

# Re-declare ARG so it's available in this stage
ARG PROFILE=lab

# Base packages — always installed
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-setuptools \
        ca-certificates \
        git \
        unzip \
        libglib2.0-0 \
        libgomp1 \
        libspatialindex-dev \
        libhdf5-dev \
        gdal-bin \
        proj-bin \
    && rm -rf /var/lib/apt/lists/*

# GRASS GIS + SAGA GIS — lab and institute profiles only
RUN case "$PROFILE" in \
        lab|institute) \
            apt-get update && apt-get install -y --no-install-recommends \
                grass saga python3-saga \
            && rm -rf /var/lib/apt/lists/* \
            ;; \
    esac

# R + IRkernel package — institute and r+julia profiles
RUN case "$PROFILE" in \
        institute|r+julia) \
            apt-get update && apt-get install -y --no-install-recommends \
                r-base r-base-dev \
            && rm -rf /var/lib/apt/lists/* \
            && Rscript -e "install.packages('IRkernel', repos='https://cloud.r-project.org', quiet=TRUE)" \
            ;; \
    esac

COPY --from=builder /venv /venv
COPY --from=builder /opt/juliaup /root/.juliaup
COPY --from=builder /opt/julia-depot /root/.julia/juliaup

ENV PATH="/root/.juliaup/bin:${PATH}"

# Kernel specs — needs Jupyter (from venv) and Julia to be present
RUN case "$PROFILE" in \
        institute|r+julia) \
            PATH=/venv/bin:$PATH Rscript -e "IRkernel::installspec(user=FALSE)" \
            ;; \
    esac

RUN if [ -f /root/.juliaup/bin/julia ]; then \
        PATH=/venv/bin:$PATH julia -e \
            'using Pkg; Pkg.add("IJulia"); using IJulia'; \
    fi

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace
EXPOSE 8888

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD [ "${GDL_MODE:-idle}" = "idle" ] || python3 -c "import socket; socket.create_connection(('localhost', 8888), 2).close()"

CMD ["/entrypoint.sh"]
