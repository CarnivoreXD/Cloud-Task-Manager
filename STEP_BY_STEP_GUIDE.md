# Cloud Task Manager — Step-by-Step Deployment Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        AWS Cloud                            │
│                                                             │
│  ┌──────────── VPC (10.0.0.0/16) ──────────────────────┐   │
│  │                                                      │   │
│  │  Public Subnets (10.0.1.0/24, 10.0.2.0/24)         │   │
│  │  ┌──────────────────────────────┐                    │   │
│  │  │  Application Load Balancer   │ ← Internet         │   │
│  │  │  (ALB via K8s Ingress)       │   Gateway          │   │
│  │  └──────────────────────────────┘                    │   │
│  │              │                                       │   │
│  │  Private Subnets (10.0.10.0/24, 10.0.11.0/24)      │   │
│  │  ┌─────────────────┐  ┌──────────────────────┐      │   │
│  │  │ EKS Worker Nodes│  │  RDS PostgreSQL      │      │   │
│  │  │ ┌─────┐ ┌─────┐│  │  (db.t3.micro)       │      │   │
│  │  │ │Pod 1│ │Pod 2││  └──────────────────────┘      │   │
│  │  │ └─────┘ └─────┘│         NAT Gateway →           │   │
│  │  │  (HPA: 2→6)    │                                 │   │
│  │  └─────────────────┘                                 │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────┐  ┌──────────────────────┐             │
│  │  AWS Cognito     │  │  Amazon ECR          │             │
│  │  (Auth + RBAC)   │  │  (Docker Registry)   │             │
│  └─────────────────┘  └──────────────────────┘             │
└─────────────────────────────────────────────────────────────┘
```

## What You'll Learn (Resume Keywords)

- **Cloud Networking**: VPC, subnets (public/private), Internet Gateway, NAT Gateway, route tables, security groups
- **Containerization**: Docker multi-stage builds, ECR image registry
- **Kubernetes (EKS)**: Deployments, Services, Ingress, HPA, Secrets, health checks
- **Cloud IAM**: AWS Cognito, OAuth 2.0, JWT validation, role-based access control
- **Infrastructure as Code**: Terraform for all AWS resources
- **CI/CD**: GitHub Actions pipeline for automated deployments
- **Managed Database**: RDS PostgreSQL in private subnet
- **Scalability**: Horizontal Pod Autoscaler (extra credit)

---

## 2-Week Timeline

| Days | Phase | What You're Doing |
|------|-------|-------------------|
| 1-2  | Phase 1 | Local setup — get app running on your machine |
| 3    | Phase 2 | Docker — containerize the app |
| 4-5  | Phase 3 | AWS prerequisites — install tools, configure CLI |
| 6-7  | Phase 4 | Terraform — deploy VPC, EKS, RDS, Cognito, ECR |
| 8-9  | Phase 5 | Deploy to EKS — push image, apply K8s manifests |
| 10   | Phase 6 | Cognito integration — test real auth flow |
| 11   | Phase 7 | Scalability demo — HPA + load test (extra credit) |
| 12-13| Phase 8 | Write report with screenshots |
| 14   | Phase 9 | Cleanup AWS resources to stop billing |

---

## Phase 1: Local Setup (Days 1-2)

### 1.1 Install Prerequisites on WSL

```bash
# Update WSL
sudo apt update && sudo apt upgrade -y

# Install Python 3.11+
sudo apt install -y python3 python3-pip python3-venv

# Verify
python3 --version   # Should be 3.10+
pip3 --version
```

### 1.2 Set Up the Project

```bash
# Navigate to your workspace
cd ~
mkdir cloud-task-manager
cd cloud-task-manager

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Copy the project files I gave you into this directory
# (or clone from your GitHub repo once you push them)

# Install dependencies
pip install -r requirements.txt
```

### 1.3 Run Locally (No Docker Yet)

```bash
# From the project root
cd app
python main.py
```

Open `http://localhost:5000` in your browser. You should see the landing page.

**📸 SCREENSHOT 1**: Landing page in browser

### 1.4 Test Local Login

Click "Get Started" → You'll see the local dev login form (since Cognito isn't configured yet).

- Log in as a **regular user** (email: `user@test.com`, role: User)
- Create 2-3 tasks
- **📸 SCREENSHOT 2**: Dashboard with tasks

- Log out, then log in as **admin** (email: `admin@test.com`, role: Admin)
- Go to the Admin panel
- **📸 SCREENSHOT 3**: Admin panel showing all tasks + audit log

### 1.5 Test the API Endpoints

```bash
# In another terminal, while the app is running:
curl http://localhost:5000/health
curl http://localhost:5000/api/metrics
```

**📸 SCREENSHOT 4**: Health check and metrics output

---

## Phase 2: Docker Containerization (Day 3)

### 2.1 Install Docker on WSL

```bash
# Install Docker
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER

# Restart WSL or run:
newgrp docker

# Verify
docker --version
docker compose version
```

### 2.2 Build and Run with Docker

```bash
# From the project root (where Dockerfile is)
cd ~/cloud-task-manager

# Build the image
docker build -t cloud-task-manager:latest .

# Run standalone container
docker run -p 5000:5000 cloud-task-manager:latest
```

Open `http://localhost:5000` — same app, now running inside a container!

**📸 SCREENSHOT 5**: App running + `docker ps` output in terminal

### 2.3 Run with Docker Compose

```bash
# Stop the standalone container (Ctrl+C)

# Use docker-compose for local dev
docker compose up --build
```

**📸 SCREENSHOT 6**: docker-compose output showing the service starting

### 2.4 Understand the Dockerfile

Open the `Dockerfile` and study each line. Key concepts to understand:

- **Multi-stage build**: Smaller production images
- **Layer caching**: `COPY requirements.txt` before `COPY app/` so dependencies are cached
- **Non-root user**: Security best practice
- **HEALTHCHECK**: Kubernetes/ECS uses this to know if the container is alive
- **Gunicorn**: Production WSGI server (not Flask's dev server)

---

## Phase 3: AWS Prerequisites (Days 4-5)

### 3.1 Install AWS CLI

```bash
# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
sudo apt install -y unzip
unzip awscliv2.zip
sudo ./aws/install

# Verify
aws --version
```

### 3.2 Configure AWS Credentials

```bash
aws configure
# Enter:
#   AWS Access Key ID: (from your AWS account)
#   AWS Secret Access Key: (from your AWS account)
#   Default region: us-west-2
#   Default output format: json
```

> ⚠️ If using AWS Academy/Learner Lab, use the temporary credentials from the Vocareum console.

### 3.3 Install Terraform

```bash
# Add HashiCorp GPG key and repo
sudo apt install -y gnupg software-properties-common
wget -O- https://apt.releases.hashicorp.com/gpg | \
    gpg --dearmor | sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null

echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
    https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
    sudo tee /etc/apt/sources.list.d/hashicorp.list

sudo apt update && sudo apt install terraform

# Verify
terraform --version
```

### 3.4 Install kubectl

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# Verify
kubectl version --client
```

### 3.5 Install eksctl (optional but helpful)

```bash
ARCH=amd64
PLATFORM=$(uname -s)_$ARCH
curl -sLO "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_$PLATFORM.tar.gz"
tar -xzf eksctl_$PLATFORM.tar.gz -C /tmp && sudo mv /tmp/eksctl /usr/local/bin

eksctl version
```

**📸 SCREENSHOT 7**: Terminal showing all tools installed (aws, terraform, kubectl, docker versions)

---

## Phase 4: Terraform — Deploy Infrastructure (Days 6-7)

### 4.1 Initialize Terraform

```bash
cd ~/cloud-task-manager/terraform

# Create a terraform.tfvars file with your DB password
echo 'db_password = "YourSecurePassword123!"' > terraform.tfvars

# Initialize (downloads AWS provider)
terraform init
```

**📸 SCREENSHOT 8**: `terraform init` success output

### 4.2 Review the Plan

```bash
terraform plan
```

This shows you everything Terraform will create. Read through it — you'll see:
- VPC with CIDR 10.0.0.0/16
- 2 public subnets + 2 private subnets
- Internet Gateway + NAT Gateway
- EKS cluster + node group
- RDS PostgreSQL instance
- Cognito User Pool + App Client
- ECR repository
- Security groups + IAM roles

**📸 SCREENSHOT 9**: Terraform plan output (showing resource count)

### 4.3 Apply (Create Everything)

```bash
terraform apply
```

Type `yes` when prompted. This takes **15-20 minutes** (EKS cluster creation is slow).

**📸 SCREENSHOT 10**: Terraform apply complete (showing outputs)

### 4.4 Save the Outputs

```bash
# Show all outputs
terraform output

# Save them for reference
terraform output > ../terraform-outputs.txt
```

Key values you'll need:
- `ecr_repository_url` — where to push your Docker image
- `eks_cluster_name` — to configure kubectl
- `cognito_user_pool_id` — for app configuration
- `cognito_client_id` — for app configuration
- `cognito_domain` — for login redirect
- `database_url` — for app to connect to RDS

**📸 SCREENSHOT 11**: AWS Console → VPC dashboard showing your VPC

**📸 SCREENSHOT 12**: AWS Console → EKS showing your cluster

**📸 SCREENSHOT 13**: AWS Console → Cognito showing your user pool

---

## Phase 5: Deploy to EKS (Days 8-9)

### 5.1 Configure kubectl for EKS

```bash
aws eks update-kubeconfig --name cloud-task-manager-eks --region us-west-2

# Verify connection
kubectl get nodes
```

You should see 2 nodes in `Ready` status.

**📸 SCREENSHOT 14**: `kubectl get nodes` output

### 5.2 Push Docker Image to ECR

```bash
# Get your ECR URL from terraform output
ECR_URL=$(cd terraform && terraform output -raw ecr_repository_url)

# Authenticate Docker to ECR
aws ecr get-login-password --region us-west-2 | \
    docker login --username AWS --password-stdin $ECR_URL

# Build and push
cd ~/cloud-task-manager
docker build -t $ECR_URL:latest .
docker push $ECR_URL:latest
```

**📸 SCREENSHOT 15**: ECR in AWS Console showing your pushed image

### 5.3 Update Kubernetes Manifests

Edit `k8s/deployment.yaml` — replace `<AWS_ACCOUNT_ID>` with your actual account ID:

```bash
# Get your account ID
aws sts get-caller-identity --query Account --output text

# Update the manifest (replace the placeholder)
sed -i "s|<AWS_ACCOUNT_ID>|$(aws sts get-caller-identity --query Account --output text)|g" k8s/deployment.yaml
```

### 5.4 Create Kubernetes Secrets

```bash
# Get values from terraform
cd terraform
DB_URL=$(terraform output -raw database_url)
POOL_ID=$(terraform output -raw cognito_user_pool_id)
CLIENT_ID=$(terraform output -raw cognito_client_id)
COGNITO_DOM=$(terraform output -raw cognito_domain)
cd ..

# Create secrets directly (easier than editing YAML)
kubectl create secret generic task-manager-secrets \
    --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
    --from-literal=DATABASE_URL="$DB_URL" \
    --from-literal=COGNITO_REGION="us-west-2" \
    --from-literal=COGNITO_USER_POOL_ID="$POOL_ID" \
    --from-literal=COGNITO_CLIENT_ID="$CLIENT_ID" \
    --from-literal=COGNITO_CLIENT_SECRET="" \
    --from-literal=COGNITO_DOMAIN="$COGNITO_DOM" \
    --from-literal=APP_URL="http://placeholder-update-later"
```

### 5.5 Deploy to Kubernetes

```bash
kubectl apply -f k8s/deployment.yaml

# Watch pods come up
kubectl get pods -w

# Check deployment status
kubectl get deployments
kubectl get services
kubectl get ingress
```

**📸 SCREENSHOT 16**: `kubectl get pods` showing 2 running pods

**📸 SCREENSHOT 17**: `kubectl get ingress` showing ALB address

### 5.6 Get Your App URL

```bash
# Wait 2-3 minutes for ALB to provision, then:
kubectl get ingress cloud-task-manager-ingress

# The ADDRESS column is your app URL
# Example: k8s-default-cloudtas-xxxxx.us-west-2.elb.amazonaws.com
```

### 5.7 Update Cognito Callback URLs

Now that you have the ALB URL, update Cognito:

```bash
APP_URL="http://YOUR-ALB-ADDRESS-HERE"

# Update the Cognito app client callback URLs
# Easiest via AWS Console:
# Cognito → User Pools → cloud-task-manager-users → App Integration → App Client
# Update:
#   Callback URL: http://YOUR-ALB-URL/callback
#   Sign-out URL: http://YOUR-ALB-URL
```

Also update the Kubernetes secret:

```bash
kubectl delete secret task-manager-secrets
# Re-create with correct APP_URL (repeat 5.4 commands with real APP_URL)
kubectl rollout restart deployment/cloud-task-manager
```

**📸 SCREENSHOT 18**: App running at ALB URL in browser

---

## Phase 6: Cognito Auth Testing (Day 10)

### 6.1 Create Test Users in Cognito

```bash
# Create admin user
aws cognito-idp admin-create-user \
    --user-pool-id $POOL_ID \
    --username admin@youremail.com \
    --user-attributes Name=email,Value=admin@youremail.com Name=email_verified,Value=true \
    --temporary-password "TempPass123!"

# Create regular user
aws cognito-idp admin-create-user \
    --user-pool-id $POOL_ID \
    --username user@youremail.com \
    --user-attributes Name=email,Value=user@youremail.com Name=email_verified,Value=true \
    --temporary-password "TempPass123!"

# Add admin user to the admin group (RBAC!)
aws cognito-idp admin-add-user-to-group \
    --user-pool-id $POOL_ID \
    --username admin@youremail.com \
    --group-name admin
```

### 6.2 Test the Full Auth Flow

1. Go to your ALB URL
2. Click "Get Started" → Redirected to Cognito Hosted UI
3. Log in as `admin@youremail.com` with temp password → Set new password
4. You should be redirected back to the dashboard
5. You should see the **Admin** badge and the Admin panel link

**📸 SCREENSHOT 19**: Cognito hosted login page

**📸 SCREENSHOT 20**: Dashboard after login (showing email and admin badge)

6. Create tasks, edit them, check the admin panel
7. Log out
8. Log in as the regular user
9. Verify they CANNOT see the Admin panel

**📸 SCREENSHOT 21**: Regular user view (no Admin link)

---

## Phase 7: Scalability Demo — Extra Credit (Day 11)

### 7.1 Verify HPA is Running

```bash
kubectl get hpa
```

**📸 SCREENSHOT 22**: HPA output showing min/max/current replicas

### 7.2 Load Test with Apache Bench

```bash
# Install ab
sudo apt install -y apache2-utils

# Generate load (1000 requests, 50 concurrent)
ab -n 1000 -c 50 http://YOUR-ALB-URL/health

# Watch pods scale up in another terminal
kubectl get pods -w
kubectl get hpa -w
```

**📸 SCREENSHOT 23**: HPA scaling up pods during load test

### 7.3 Explain Scalability in Report

In your report, explain:
- HPA monitors CPU utilization across pods
- When CPU > 70%, HPA adds more pods (up to 6)
- ALB distributes traffic across all pods
- EKS node group can scale from 1→3 nodes if needed
- RDS handles database scaling independently

---

## Phase 8: Write Report (Days 12-13)

Your .docx report should include these sections:

1. **Project Overview** — What you built and why
2. **Architecture Diagram** — Include the ASCII diagram above or draw one
3. **Technology Stack** — Python/Flask, Docker, Kubernetes, Terraform, AWS services
4. **Cloud Access Management** — How Cognito handles auth, how groups enable RBAC
5. **Networking** — VPC design, public vs private subnets, security groups
6. **Deployment Process** — Docker → ECR → EKS flow
7. **Scalability** — HPA configuration and load test results
8. **Screenshots** — All the screenshots from above
9. **GitHub Link** — Link to your repository
10. **Lessons Learned** — What you learned about cloud fundamentals

---

## Phase 9: Cleanup (Day 14)

**CRITICAL — Do this to avoid charges!**

```bash
# Delete Kubernetes resources first
kubectl delete -f k8s/deployment.yaml
kubectl delete secret task-manager-secrets

# Destroy all Terraform-managed infrastructure
cd ~/cloud-task-manager/terraform
terraform destroy
```

Type `yes` when prompted. This deletes:
- VPC and all networking
- EKS cluster and nodes
- RDS database
- Cognito user pool
- ECR repository

**Estimated cost if left running**: ~$70-100/month (EKS + RDS + NAT Gateway)

---

## Troubleshooting

### "502 Bad Gateway" from ALB
```bash
# Check pod logs
kubectl logs -l app=cloud-task-manager --tail=50
# Common cause: database connection. Check RDS security group allows traffic from EKS.
```

### Cognito login redirects but callback fails
- Double-check callback URL in Cognito matches your ALB URL exactly
- Make sure APP_URL in Kubernetes secret matches too
- Verify COGNITO_CLIENT_SECRET is set if your app client generates one

### Terraform apply fails
```bash
terraform refresh     # Sync state
terraform plan        # Check what's different
terraform apply       # Retry
```

### Docker push to ECR fails
```bash
# Re-authenticate (tokens expire after 12 hours)
aws ecr get-login-password --region us-west-2 | \
    docker login --username AWS --password-stdin $ECR_URL
```

### Pods stuck in CrashLoopBackOff
```bash
kubectl describe pod <pod-name>    # Check events
kubectl logs <pod-name>            # Check app errors
```

---

## Quick Reference Commands

```bash
# --- Terraform ---
cd terraform && terraform output              # See all outputs
terraform output -raw ecr_repository_url      # Get specific value

# --- Docker ---
docker build -t cloud-task-manager .          # Build
docker run -p 5000:5000 cloud-task-manager    # Run locally

# --- Kubernetes ---
kubectl get pods                              # List pods
kubectl get svc                               # List services
kubectl get ingress                           # Get ALB URL
kubectl logs -l app=cloud-task-manager -f     # Stream logs
kubectl describe pod <name>                   # Debug pod
kubectl rollout restart deploy/cloud-task-manager  # Redeploy

# --- Cognito ---
aws cognito-idp list-users --user-pool-id $POOL_ID
aws cognito-idp admin-add-user-to-group --user-pool-id $POOL_ID --username EMAIL --group-name admin
```
