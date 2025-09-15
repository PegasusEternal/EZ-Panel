# Base image: Kali Linux
FROM kalilinux/kali-rolling

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    iputils-ping \
    net-tools \
    nmap \
    tcpdump \
    vim \
    git \
    && apt-get clean

# Create a symlink for `python` pointing to `python3`
RUN ln -s /usr/bin/python3 /usr/bin/python

# Create a virtual environment
RUN python3 -m venv /app/venv

# Activate the virtual environment and install Python dependencies
COPY requirements.txt .
RUN /app/venv/bin/pip install --no-cache-dir -v -r requirements.txt

# Copy the full application
COPY . .

# Set the virtual environment as the default Python environment
ENV PATH="/app/venv/bin:$PATH"

# Expose Flask port
EXPOSE 5000

# Default command to run Flask
CMD ["python", "-m", "ez_panel.app"]