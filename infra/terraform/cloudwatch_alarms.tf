# ── CloudWatch Alarms for Complyra ────────────────────────────────
# Production monitoring alarms for ECS services and ALB.

resource "aws_sns_topic" "alarms" {
  name = "${local.name_prefix}-alarms"
  tags = local.tags
}

# ── ECS Service Alarms ───────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "api_cpu_high" {
  alarm_name          = "${local.name_prefix}-api-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "API service CPU utilization above 80% for 3 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.this.name
    ServiceName = "${local.name_prefix}-api"
  }

  tags = local.tags
}

resource "aws_cloudwatch_metric_alarm" "api_memory_high" {
  alarm_name          = "${local.name_prefix}-api-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "API service memory utilization above 85% for 3 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.this.name
    ServiceName = "${local.name_prefix}-api"
  }

  tags = local.tags
}

resource "aws_cloudwatch_metric_alarm" "worker_cpu_high" {
  alarm_name          = "${local.name_prefix}-worker-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "Worker service CPU above 85% for 3 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.this.name
    ServiceName = "${local.name_prefix}-worker"
  }

  tags = local.tags
}

# ── ALB Alarms ────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "alb_5xx_rate" {
  alarm_name          = "${local.name_prefix}-alb-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "ALB target 5xx count above 10 per minute for 3 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.app.arn_suffix
  }

  tags = local.tags
}

resource "aws_cloudwatch_metric_alarm" "alb_target_response_time" {
  alarm_name          = "${local.name_prefix}-alb-response-time-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "p95"
  threshold           = 5
  alarm_description   = "ALB target response time p95 above 5s for 3 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.app.arn_suffix
  }

  tags = local.tags
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  alarm_name          = "${local.name_prefix}-alb-unhealthy-hosts"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "ALB has unhealthy targets for 2 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer  = aws_lb.app.arn_suffix
    TargetGroup   = aws_lb_target_group.api.arn_suffix
  }

  tags = local.tags
}

# ── CloudWatch Log Metric Filters ────────────────────────────────

resource "aws_cloudwatch_log_metric_filter" "api_errors" {
  name           = "${local.name_prefix}-api-error-count"
  pattern        = "{ $.level = \"ERROR\" }"
  log_group_name = "/ecs/${local.name_prefix}/api"

  metric_transformation {
    name      = "APIErrorCount"
    namespace = "Complyra/Application"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "api_error_log_rate" {
  alarm_name          = "${local.name_prefix}-api-error-log-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "APIErrorCount"
  namespace           = "Complyra/Application"
  period              = 300
  statistic           = "Sum"
  threshold           = 50
  alarm_description   = "More than 50 ERROR log entries in 5 minutes for 3 consecutive periods"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  tags = local.tags
}
