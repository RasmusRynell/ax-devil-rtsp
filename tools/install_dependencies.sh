#!/bin/bash
# Complete installation script for ax-devil-rtsp
# Based on analysis of .github/workflows/publish.yml, pyproject.toml, and tools/check_dependencies.py

echo "🔧 Setting up ax-devil-rtsp development environment..."

# Create and activate virtual environment
echo "📦 Setting up Python virtual environment..."
python -m pip install --upgrade pip
python -m venv .venv
source .venv/bin/activate

# Update system packages
echo "🔄 Updating system packages..."
sudo apt-get update

# Install core system dependencies for PyGObject and GStreamer
echo "🛠️ Installing system dependencies..."
sudo apt-get install -y --no-install-recommends \
    libgirepository-2.0-dev \
    gobject-introspection \
    libcairo2-dev \
    libffi-dev \
    pkg-config \
    gcc \
    libglib2.0-dev

# Install comprehensive GStreamer packages
echo "🎥 Installing GStreamer packages..."
sudo apt-get install -y \
    gstreamer1.0-dev \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-tools \
    gstreamer1.0-rtsp \
    libgstrtspserver-1.0-0

# Install GObject introspection packages for GStreamer
echo "🔗 Installing GObject introspection packages..."
sudo apt-get install -y \
    gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gst-rtsp-server-1.0

# Install additional GStreamer plugins and tools
echo "📺 Installing additional GStreamer components..."
sudo apt-get install -y \
    gstreamer1.0-x \
    gstreamer1.0-alsa \
    gstreamer1.0-gl \
    gstreamer1.0-gtk3 \
    gstreamer1.0-qt5 \
    gstreamer1.0-pulseaudio \
    python3-gi \
    python3-gst-1.0

# Install display server for headless testing (if needed)
echo "🖥️ Installing display server for testing..."
sudo apt-get install -y xvfb

# Install Python dependencies for PyGObject
echo "🐍 Installing Python PyGObject dependencies..."
pip install pycairo PyGObject

# Install project dependencies
echo "📚 Installing project dependencies..."
if [ -f requirements.txt ]; then 
    echo "   Found requirements.txt, installing..."
    pip install -r requirements.txt
fi

if [ -f requirements-dev.txt ]; then 
    echo "   Found requirements-dev.txt, installing..."
    pip install -r requirements-dev.txt
fi

# Install the project in development mode with dev extras
echo "⚙️ Installing ax-devil-rtsp in development mode..."
pip install -e .[dev]

# Verify installation
echo "🔍 Verifying installation..."
python tools/check_dependencies.py

echo "✅ Installation complete!"
echo ""
echo "📋 Next steps:"
echo "   1. Activate virtual environment: source .venv/bin/activate"
echo "   2. Run tests: pytest tests/ -v"
echo "   3. For integration tests with real camera: USE_REAL_CAMERA=true pytest tests/integration/ -v"
echo "   4. For local testing: USE_REAL_CAMERA=false pytest tests/ -v" 