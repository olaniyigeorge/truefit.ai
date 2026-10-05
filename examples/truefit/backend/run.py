#!/usr/bin/env python
"""Run the Truefit API server with proper Python path configuration."""

import os
import sys
import subprocess

# Add the backend directory and src/ to Python path (mirrors tests/pytest.ini's `pythonpath = . src`)
backend_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(backend_dir, 'src')
sys.path.insert(0, backend_dir)
sys.path.insert(0, src_dir)
os.environ['PYTHONPATH'] = os.pathsep.join([backend_dir, src_dir])

# Run uvicorn
subprocess.run([
    sys.executable, '-m', 'uvicorn',
    'src.truefit_api.main:app',
    '--host', '0.0.0.0',
    '--port', '8000',
    '--reload'
])
