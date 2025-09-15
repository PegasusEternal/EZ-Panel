FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-venv \
       python3-pip \
       git \
       curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspaces

EXPOSE 5000
