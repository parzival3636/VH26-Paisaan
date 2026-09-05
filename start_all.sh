#!/bin/bash

# Intelligent Pipeline Demo - Quick Start Script
# This script starts all services needed for the demo

echo "🚀 Starting Intelligent Pipeline Demo..."
echo ""

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found. Please install Docker and Docker Compose first."
    exit 1
fi

# Check if Python is available
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "❌ Python not found. Please install Python 3.8+ first."
    exit 1
fi

# Check if npm is available
if ! command -v npm &> /dev/null; then
    echo "❌ npm not found. Please install Node.js and npm first."
    exit 1
fi

echo "✅ All prerequisites found"
echo ""

# Start infrastructure
echo "📦 Starting Docker services (Kafka, Redis, Zookeeper)..."
docker-compose up -d
if [ $? -ne 0 ]; then
    echo "❌ Failed to start Docker services"
    exit 1
fi
echo "✅ Docker services started"
echo ""

# Wait for services to be ready
echo "⏳ Waiting for services to be ready (10 seconds)..."
sleep 10
echo ""

# Start backend in background
echo "🔧 Starting Backend Pipeline..."
PYTHON_CMD=$(command -v python3 || command -v python)
$PYTHON_CMD pipeline/main.py > pipeline.log 2>&1 &
BACKEND_PID=$!
echo "✅ Backend started (PID: $BACKEND_PID, logs: pipeline.log)"
echo ""

# Wait for backend to start
echo "⏳ Waiting for backend to initialize (5 seconds)..."
sleep 5
echo ""

# Start frontend
echo "🎨 Starting Frontend..."
cd frontend/frontend
npm run dev &
FRONTEND_PID=$!
cd ../..
echo "✅ Frontend started (PID: $FRONTEND_PID)"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ All services started successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📍 Access the demo at: http://localhost:5174"
echo "📍 Backend API: http://localhost:8000"
echo "📍 API Docs: http://localhost:8000/docs"
echo ""
echo "📋 Service PIDs:"
echo "   Backend: $BACKEND_PID"
echo "   Frontend: $FRONTEND_PID"
echo ""
echo "To stop all services, run: ./stop_all.sh"
echo "Or manually:"
echo "   kill $BACKEND_PID $FRONTEND_PID"
echo "   docker-compose down"
echo ""
