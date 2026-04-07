#!/usr/bin/env python
"""Run the Truefit API server with proper Python path configuration."""

import os
import sys
import subprocess

# Add the backend directory to Python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)
os.environ['PYTHONPATH'] = backend_dir

# Run uvicorn
subprocess.run([
    sys.executable, '-m', 'uvicorn',
    'src.truefit_api.main:app',
    '--host', '0.0.0.0',
    '--port', '8000',
    '--reload'
])
