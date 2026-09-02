"""
Serverless entry point for Vercel Python Functions and AWS Lambda.
"""
from trader.main import app

try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    handler = None
