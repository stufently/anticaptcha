#!/bin/bash
# Run anticaptcha service in Docker

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="anticaptcha"
CONTAINER_NAME="anticaptcha-api"

# Build Docker image
echo "🔨 Building Docker image..."
docker build -t $IMAGE_NAME $PROJECT_ROOT

# Stop existing container if running
if docker ps -q --filter "name=$CONTAINER_NAME" | grep -q .; then
    echo "🛑 Stopping existing container..."
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
fi

# Run API server
echo "🚀 Starting API server..."
docker run -d \
    --name $CONTAINER_NAME \
    -p 127.0.0.1:8000:8000 \
    -v $PROJECT_ROOT/data:/app/data \
    $IMAGE_NAME

echo "✅ Service started!"
echo "📖 API docs: http://localhost:8000/docs"
echo "🔍 Health check: http://localhost:8000/health"

# Wait for service to start
sleep 3
curl -s http://localhost:8000/health || echo "⚠️ Service not ready yet"