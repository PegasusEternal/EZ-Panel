#!/bin/bash

# 1. Check if Docker image exists
if [[ "$(docker images -q c2panel 2> /dev/null)" == "" ]]; then
    echo "Building Docker image..."
    docker build -t c2panel .
fi

# 2. Run the Docker container
echo "Starting EZ-Panel..."
docker run -it -p 5000:5000 --rm c2panel
