# Cloud Task Manager

A cloud-native task management application demonstrating AWS cloud fundamentals including networking, containerization, Kubernetes orchestration, and IAM-based access control.

## Architecture

- **Application**: Python Flask with SQLAlchemy ORM
- **Authentication**: AWS Cognito (OAuth 2.0 + JWT)
- **Access Control**: Role-Based (admin/user) via Cognito Groups
- **Container**: Docker with multi-stage build → Amazon ECR
- **Orchestration**: Amazon EKS (Kubernetes) with HPA auto-scaling
- **Database**: Amazon RDS PostgreSQL (private subnet)
- **Networking**: Custom VPC with public/private subnets, ALB, NAT Gateway
- **IaC**: Terraform for all AWS infrastructure
- **CI/CD**: GitHub Actions → ECR → EKS

## Quick Start (Local Development)

```bash
# Clone and setup
git clone https://github.com/YOUR-USERNAME/cloud-task-manager.git
cd cloud-task-manager

# Option A: Python directly
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd app && python main.py

# Option B: Docker Compose
docker compose up --build
```

Visit `http://localhost:5000` — uses local dev login (no Cognito needed).

## Cloud Deployment

See [STEP_BY_STEP_GUIDE.md](STEP_BY_STEP_GUIDE.md) for the full deployment walkthrough.

## Project Structure

```
cloud-task-manager/
├── app/
│   ├── main.py              # Flask application (routes, models, auth)
│   ├── templates/           # Jinja2 HTML templates
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── dashboard.html
│   │   ├── task_form.html
│   │   ├── admin.html
│   │   └── login_local.html
│   └── static/css/style.css
├── terraform/
│   └── main.tf              # VPC, EKS, RDS, Cognito, ECR
├── k8s/
│   ├── deployment.yaml      # Deployment, Service, Ingress, HPA
│   └── secrets.yaml         # Template for K8s secrets
├── .github/workflows/
│   └── deploy.yml           # CI/CD pipeline
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── STEP_BY_STEP_GUIDE.md
```

## Key Features

| Feature | Implementation |
|---------|---------------|
| Cloud IAM | AWS Cognito OAuth 2.0 with JWT validation |
| RBAC | Cognito Groups (admin group → admin panel access) |
| Containerization | Docker + Gunicorn WSGI server |
| Orchestration | EKS Deployment with 2 replicas |
| Auto-Scaling | HPA scales 2→6 pods at 70% CPU |
| Cloud Networking | VPC, public/private subnets, ALB, NAT GW |
| Health Checks | /health endpoint for K8s liveness/readiness |
| Monitoring | /api/metrics Prometheus-compatible endpoint |
| Audit Logging | All CRUD actions logged with timestamps |
| IaC | Terraform manages all AWS resources |
| CI/CD | GitHub Actions → ECR → EKS on push to main |

## Technologies

Python, Flask, SQLAlchemy, Docker, Kubernetes, Terraform, AWS (EKS, ECR, RDS, Cognito, VPC, ALB, IAM), GitHub Actions
