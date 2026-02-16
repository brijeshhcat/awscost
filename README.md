# AWS Cost Optimization Tool

A Flask-based dashboard for AWS cost management, optimization recommendations, resource inventory, savings plans, cost forecasting, and latest AWS news.

## Features

| Page | Description |
|------|-------------|
| **Dashboard** | 30-day cost summary, daily trend chart, top services breakdown, cost anomalies |
| **Recommendations** | EC2 rightsizing, Trusted Advisor cost checks, idle/unused resource detection |
| **Resource Inventory** | EC2, RDS, S3, Lambda, EBS, EIP, ALB/NLB, VPC, DynamoDB, ECS |
| **Savings Plans / RI** | Active plans & RIs, coverage, utilization, purchase recommendations |
| **Forecast** | Historical monthly trends + AWS Cost Explorer forecast with confidence bands |
| **AWS News** | Live feed from AWS Blog, What's New, and Cloud Financial Management RSS |

## Prerequisites

- Python 3.9+
- AWS credentials with permissions for Cost Explorer, EC2, RDS, S3, Lambda, CloudWatch, ELB, Support (for Trusted Advisor), Savings Plans

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set AWS credentials (or use IAM role on EC2/ECS)
export AWS_ACCESS_KEY_ID=your-key
export AWS_SECRET_ACCESS_KEY=your-secret
export AWS_REGION=us-east-1          # optional, defaults to us-east-1

# 3. Run the app
python app.py
```

Open **http://localhost:5000** in your browser.

## Project Structure

```
awscost/
├── app.py                    # Flask routes & API endpoints
├── config.py                 # Configuration (env vars)
├── requirements.txt
├── aws_services/
│   ├── __init__.py
│   ├── cost_explorer.py      # Cost data, anomalies, forecast
│   ├── recommendations.py    # Rightsizing, Trusted Advisor, idle resources
│   ├── inventory.py          # Multi-service resource inventory
│   ├── savings_plans.py      # Savings Plans & Reserved Instances
│   └── news.py               # AWS RSS news aggregator
├── templates/
│   ├── base.html             # Shared layout with sidebar nav
│   ├── dashboard.html
│   ├── recommendations.html
│   ├── inventory.html
│   ├── savings_plans.html
│   ├── forecast.html
│   └── news.html
└── static/
    └── css/
        └── style.css
```

## Required AWS IAM Permissions

```json
{
  "Effect": "Allow",
  "Action": [
    "ce:GetCostAndUsage",
    "ce:GetCostForecast",
    "ce:GetAnomalies",
    "ce:GetRightsizingRecommendation",
    "ce:GetSavingsPlansCoverage",
    "ce:GetSavingsPlansUtilization",
    "ce:GetSavingsPlansPurchaseRecommendation",
    "ec2:DescribeInstances",
    "ec2:DescribeVolumes",
    "ec2:DescribeAddresses",
    "ec2:DescribeVpcs",
    "ec2:DescribeReservedInstances",
    "rds:DescribeDBInstances",
    "rds:DescribeReservedDBInstances",
    "s3:ListAllMyBuckets",
    "s3:GetBucketLocation",
    "lambda:ListFunctions",
    "elasticloadbalancing:DescribeLoadBalancers",
    "dynamodb:ListTables",
    "dynamodb:DescribeTable",
    "ecs:ListClusters",
    "ecs:DescribeClusters",
    "cloudwatch:GetMetricStatistics",
    "savingsplans:DescribeSavingsPlans",
    "support:DescribeTrustedAdvisorChecks",
    "support:DescribeTrustedAdvisorCheckResult"
  ],
  "Resource": "*"
}
```
