# ============================================================
# Cloud Task Manager - AWS Infrastructure (Terraform)
# Creates: VPC, EKS Cluster, ECR, Cognito, RDS
# ============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ============================================================
# Variables
# ============================================================
variable "aws_region" {
  default = "us-west-2"
}

variable "project_name" {
  default = "cloud-task-manager"
}

variable "db_password" {
  description = "RDS database password"
  type        = string
  sensitive   = true
}

# Get current account ID
data "aws_caller_identity" "current" {}

# Get available AZs
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

# ============================================================
# VPC + Networking
# This is where you learn cloud networking fundamentals:
# - VPC = your own isolated network in the cloud
# - Public subnets = accessible from internet (load balancer)
# - Private subnets = no direct internet access (app + DB)
# - NAT Gateway = lets private subnets reach internet outbound
# - Internet Gateway = connects VPC to the internet
# ============================================================
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${var.project_name}-vpc" }
}

# Internet Gateway - connects VPC to the internet
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project_name}-igw" }
}

# Public Subnets (for ALB / Load Balancer)
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index + 1}.0/24"
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                                           = "${var.project_name}-public-${count.index + 1}"
    "kubernetes.io/role/elb"                       = "1"
    "kubernetes.io/cluster/${var.project_name}-eks" = "owned"
  }
}

# Private Subnets (for EKS pods and RDS)
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 10}.0/24"
  availability_zone = local.azs[count.index]

  tags = {
    Name                                           = "${var.project_name}-private-${count.index + 1}"
    "kubernetes.io/role/internal-elb"              = "1"
    "kubernetes.io/cluster/${var.project_name}-eks" = "owned"
  }
}

# NAT Gateway (lets private subnets reach internet for pulling images etc.)
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${var.project_name}-nat-eip" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = "${var.project_name}-nat" }
  depends_on    = [aws_internet_gateway.main]
}

# Route Tables
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${var.project_name}-public-rt" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
  tags = { Name = "${var.project_name}-private-rt" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ============================================================
# Security Groups
# ============================================================
resource "aws_security_group" "eks_cluster" {
  name_prefix = "${var.project_name}-eks-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-eks-sg" }
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.project_name}-rds-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.eks_cluster.id]
  }

  tags = { Name = "${var.project_name}-rds-sg" }
}

# ============================================================
# ECR - Container Registry (stores your Docker image)
# ============================================================
resource "aws_ecr_repository" "app" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = var.project_name }
}

# ============================================================
# EKS Cluster (Kubernetes on AWS)
# ============================================================
resource "aws_iam_role" "eks_cluster" {
  name = "${var.project_name}-eks-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.eks_cluster.name
}

resource "aws_eks_cluster" "main" {
  name     = "${var.project_name}-eks"
  role_arn = aws_iam_role.eks_cluster.arn
  version  = "1.29"

  vpc_config {
    subnet_ids              = concat(aws_subnet.public[*].id, aws_subnet.private[*].id)
    security_group_ids      = [aws_security_group.eks_cluster.id]
    endpoint_public_access  = true
    endpoint_private_access = true
  }

  depends_on = [aws_iam_role_policy_attachment.eks_cluster_policy]
}

# EKS Node Group (worker nodes where your pods run)
resource "aws_iam_role" "eks_nodes" {
  name = "${var.project_name}-eks-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_worker" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_cni" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_ecr" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.project_name}-nodes"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = aws_subnet.private[*].id

  scaling_config {
    desired_size = 2
    min_size     = 1
    max_size     = 3
  }

  instance_types = ["t3.small"]  # Cost-effective for a demo

  depends_on = [
    aws_iam_role_policy_attachment.eks_worker,
    aws_iam_role_policy_attachment.eks_cni,
    aws_iam_role_policy_attachment.eks_ecr,
  ]
}

# ============================================================
# RDS PostgreSQL (managed database)
# ============================================================
resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier             = "${var.project_name}-db"
  engine                 = "postgres"
  engine_version         = "15"
  instance_class         = "db.t3.micro"  # Free tier eligible
  allocated_storage      = 20
  db_name                = "taskmanager"
  username               = "taskuser"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = true
  publicly_accessible    = false

  tags = { Name = "${var.project_name}-rds" }
}

# ============================================================
# Cognito User Pool (Cloud IAM / Authentication)
# ============================================================
resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name}-users"

  # Email/password signup
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_symbols   = false
    require_uppercase = true
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  tags = { Name = var.project_name }
}

# Cognito Domain (for hosted login UI)
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project_name}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

# Cognito App Client
resource "aws_cognito_user_pool_client" "main" {
  name                                 = "${var.project_name}-client"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  allowed_oauth_flows_user_pool_client = true
  supported_identity_providers         = ["COGNITO"]

  # UPDATE these after you get the ALB URL
  callback_urls = ["http://localhost:5000/callback"]
  logout_urls   = ["http://localhost:5000"]
}

# Admin group for RBAC
resource "aws_cognito_user_group" "admin" {
  name         = "admin"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Administrators with full access"
}

# ============================================================
# Outputs - Values you'll need for deployment
# ============================================================
output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "eks_cluster_name" {
  value = aws_eks_cluster.main.name
}

output "eks_cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.main.id
}

output "cognito_domain" {
  value = "${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "rds_endpoint" {
  value = aws_db_instance.main.endpoint
}

output "database_url" {
  value     = "postgresql://taskuser:${var.db_password}@${aws_db_instance.main.endpoint}/taskmanager"
  sensitive = true
}

output "vpc_id" {
  value = aws_vpc.main.id
}
