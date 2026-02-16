import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'aws-cost-optimizer-secret')
    AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    # Optional: Use IAM Role if running on EC2/ECS (recommended)