#!/bin/bash

# Intelligent Pipeline Demo - Stop Script

echo "🛑 Stopping Intelligent Pipeline Demo..."
echo ""

# Stop Docker services
echo "📦 Stopping Docker services..."
docker-compose down
echo "✅ Docker services stopped"
echo ""

# Kill any Python processes running main.py
echo "🔧 Stopping Backend..."
pkill -f "python.*pipeline/main.py" || pkill -f "python3.*pipeline/main.py"
echo "✅ Backend stopped"
echo ""

# Kill any npm dev servers
echo "🎨 Stopping Frontend..."
pkill -f "vite" || pkill -f "npm.*dev"
echo "✅ Frontend stopped"
echo ""

echo "✨ All services stopped successfully!"
