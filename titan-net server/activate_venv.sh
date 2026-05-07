#!/bin/bash
# Activate virtual environment on server
# Usage: source activate_venv.sh

echo "Activating Titan-Net virtual environment..."
source /opt/titan-net/venv/bin/activate
echo "Virtual environment activated!"
echo "Python: $(which python)"
echo "Pip: $(which pip)"
