output "vpc_id" {
  description = "Complyra VPC ID"
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.this.name
}

output "security_group_ids" {
  description = "Security groups for Complyra services"
  value = {
    alb    = aws_security_group.alb.id
    api    = aws_security_group.api.id
    web    = aws_security_group.web.id
    worker = aws_security_group.worker.id
    rds    = aws_security_group.rds.id
    redis  = aws_security_group.redis.id
    ollama = aws_security_group.ollama.id
  }
}

output "alb_dns_name" {
  description = "ALB DNS name"
  value       = aws_lb.app.dns_name
}

output "api_target_group_arn" {
  description = "API target group ARN"
  value       = aws_lb_target_group.api.arn
}

output "web_target_group_arn" {
  description = "Web target group ARN"
  value       = aws_lb_target_group.web.arn
}

output "rds_endpoint" {
  description = "RDS endpoint"
  value       = aws_db_instance.postgres.address
}

output "redis_primary_endpoint" {
  description = "ElastiCache primary endpoint"
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "ecs_service_names" {
  description = "ECS service names"
  value = {
    api    = aws_ecs_service.api.name
    worker = aws_ecs_service.worker.name
    web    = aws_ecs_service.web.name
  }
}

output "ecs_task_execution_role_arn" {
  description = "ECS task execution role ARN"
  value       = aws_iam_role.ecs_task_execution.arn
}

output "ecs_task_role_arn" {
  description = "ECS task role ARN"
  value       = aws_iam_role.ecs_task.arn
}

output "jwt_secret_arn" {
  description = "Secrets Manager ARN for JWT secret"
  value       = aws_secretsmanager_secret.jwt.arn
}

output "sentry_secret_arn" {
  description = "Secrets Manager ARN for Sentry DSN if configured"
  value       = var.app_sentry_dsn != "" ? aws_secretsmanager_secret.sentry[0].arn : null
  sensitive   = true
}

output "synthetics_canary_name" {
  description = "CloudWatch Synthetics canary name"
  value       = var.enable_synthetics ? aws_synthetics_canary.login_chat_approval[0].name : null
}

output "synthetics_canary_arn" {
  description = "CloudWatch Synthetics canary ARN"
  value       = var.enable_synthetics ? aws_synthetics_canary.login_chat_approval[0].arn : null
}
