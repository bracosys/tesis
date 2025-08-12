#!/usr/bin/env python
"""
WSGI entry point for production deployment
"""
import os
import sys

# Add the project directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from app import app
    
    if __name__ == "__main__":
        app.run()
        
except ImportError as e:
    print(f"Error importing app: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error starting application: {e}")
    sys.exit(1)
