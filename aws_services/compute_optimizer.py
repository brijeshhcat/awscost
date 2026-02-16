"""
AWS Compute Optimizer Service
Retrieves optimization recommendations for EC2, EBS, Lambda, ECS, and Auto Scaling.
"""

from aws_services.account_manager import get_session


class ComputeOptimizerService:
    def __init__(self):
        pass

    @property
    def session(self):
        return get_session()

    @property
    def co(self):
        return self.session.client("compute-optimizer")

    # ------------------------------------------------------------------ #
    #  Enrollment Status
    # ------------------------------------------------------------------ #
    def get_enrollment_status(self):
        try:
            resp = self.co.get_enrollment_status()
            return {
                "status": resp.get("status", "Inactive"),
                "member_accounts_enrolled": resp.get("memberAccountsEnrolled", False),
                "last_updated": str(resp.get("lastUpdatedTimestamp", "")),
            }
        except Exception as e:
            return {"status": "Error", "error": str(e)}

    # ------------------------------------------------------------------ #
    #  EC2 Instance Recommendations
    # ------------------------------------------------------------------ #
    def get_ec2_recommendations(self):
        try:
            resp = self.co.get_ec2_instance_recommendations()
            recommendations = []
            for rec in resp.get("instanceRecommendations", []):
                current = rec.get("currentInstanceType", "N/A")
                finding = rec.get("finding", "")
                utilization = rec.get("utilizationMetrics", [])

                # Extract CPU and memory utilization
                cpu_util = "N/A"
                mem_util = "N/A"
                for m in utilization:
                    if m.get("name") == "CPU":
                        cpu_util = f"{round(float(m.get('value', 0)), 1)}%"
                    elif m.get("name") == "MEMORY":
                        mem_util = f"{round(float(m.get('value', 0)), 1)}%"

                # Get top recommendation option
                options = rec.get("recommendationOptions", [])
                top_option = options[0] if options else {}
                recommended_type = top_option.get("instanceType", "N/A")

                # Performance risk
                perf_risk = top_option.get("performanceRisk", 0)

                # Estimated savings
                savings_opportunity = top_option.get("savingsOpportunity", {})
                savings_pct = savings_opportunity.get("savingsOpportunityPercentage", 0)
                est_monthly_savings = float(
                    savings_opportunity.get("estimatedMonthlySavings", {})
                    .get("value", 0)
                )

                # Instance ARN to extract ID
                arn = rec.get("instanceArn", "")
                instance_id = arn.split("/")[-1] if "/" in arn else arn

                # Tags / Name
                instance_name = rec.get("instanceName", "")

                recommendations.append({
                    "instance_id": instance_id,
                    "instance_name": instance_name,
                    "account_id": rec.get("accountId", ""),
                    "current_type": current,
                    "finding": finding,
                    "finding_reasons": rec.get("findingReasonCodes", []),
                    "cpu_utilization": cpu_util,
                    "memory_utilization": mem_util,
                    "recommended_type": recommended_type,
                    "performance_risk": perf_risk,
                    "savings_pct": round(savings_pct, 1),
                    "est_monthly_savings": round(est_monthly_savings, 2),
                    "migration_effort": top_option.get("migrationEffort", "N/A"),
                    "recommendation_options": [
                        {
                            "instance_type": opt.get("instanceType", ""),
                            "perf_risk": opt.get("performanceRisk", 0),
                            "savings_pct": round(
                                opt.get("savingsOpportunity", {})
                                .get("savingsOpportunityPercentage", 0), 1
                            ),
                            "est_monthly_savings": round(float(
                                opt.get("savingsOpportunity", {})
                                .get("estimatedMonthlySavings", {})
                                .get("value", 0)
                            ), 2),
                        }
                        for opt in options[:3]  # Top 3 options
                    ],
                })

            total_savings = sum(r["est_monthly_savings"] for r in recommendations)
            return {
                "recommendations": recommendations,
                "total_monthly_savings": round(total_savings, 2),
                "count": len(recommendations),
                "over_provisioned": len([r for r in recommendations if r["finding"] == "OVER_PROVISIONED"]),
                "under_provisioned": len([r for r in recommendations if r["finding"] == "UNDER_PROVISIONED"]),
                "optimized": len([r for r in recommendations if r["finding"] == "OPTIMIZED"]),
            }
        except Exception as e:
            return {
                "recommendations": [], "total_monthly_savings": 0,
                "count": 0, "over_provisioned": 0, "under_provisioned": 0,
                "optimized": 0, "error": str(e),
            }

    # ------------------------------------------------------------------ #
    #  EBS Volume Recommendations
    # ------------------------------------------------------------------ #
    def get_ebs_recommendations(self):
        try:
            resp = self.co.get_ebs_volume_recommendations()
            recommendations = []
            for rec in resp.get("volumeRecommendations", []):
                current_config = rec.get("currentConfiguration", {})
                finding = rec.get("finding", "")

                options = rec.get("volumeRecommendationOptions", [])
                top_option = options[0] if options else {}
                top_config = top_option.get("configuration", {})

                savings_opportunity = top_option.get("savingsOpportunity", {})
                est_monthly_savings = float(
                    savings_opportunity.get("estimatedMonthlySavings", {})
                    .get("value", 0)
                )

                vol_arn = rec.get("volumeArn", "")
                vol_id = vol_arn.split("/")[-1] if "/" in vol_arn else vol_arn

                recommendations.append({
                    "volume_id": vol_id,
                    "account_id": rec.get("accountId", ""),
                    "finding": finding,
                    "current_type": current_config.get("volumeType", "N/A"),
                    "current_size": current_config.get("volumeSize", 0),
                    "current_iops": current_config.get("volumeBaselineIOPS", 0),
                    "current_throughput": current_config.get("volumeBaselineThroughput", 0),
                    "recommended_type": top_config.get("volumeType", "N/A"),
                    "recommended_size": top_config.get("volumeSize", 0),
                    "recommended_iops": top_config.get("volumeBaselineIOPS", 0),
                    "savings_pct": round(
                        savings_opportunity.get("savingsOpportunityPercentage", 0), 1
                    ),
                    "est_monthly_savings": round(est_monthly_savings, 2),
                })

            total_savings = sum(r["est_monthly_savings"] for r in recommendations)
            return {
                "recommendations": recommendations,
                "total_monthly_savings": round(total_savings, 2),
                "count": len(recommendations),
            }
        except Exception as e:
            return {"recommendations": [], "total_monthly_savings": 0, "count": 0, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Lambda Function Recommendations
    # ------------------------------------------------------------------ #
    def get_lambda_recommendations(self):
        try:
            resp = self.co.get_lambda_function_recommendations()
            recommendations = []
            for rec in resp.get("lambdaFunctionRecommendations", []):
                current_config = rec.get("currentMemorySize", 0)
                finding = rec.get("finding", "")
                finding_reasons = rec.get("findingReasonCodes", [])

                func_arn = rec.get("functionArn", "")
                func_name = func_arn.split(":")[-1] if ":" in func_arn else func_arn

                options = rec.get("memorySizeRecommendationOptions", [])
                top_option = options[0] if options else {}

                savings_opportunity = top_option.get("savingsOpportunity", {})
                est_monthly_savings = float(
                    savings_opportunity.get("estimatedMonthlySavings", {})
                    .get("value", 0)
                )

                recommendations.append({
                    "function_name": func_name,
                    "function_arn": func_arn,
                    "account_id": rec.get("accountId", ""),
                    "finding": finding,
                    "finding_reasons": finding_reasons,
                    "current_memory_mb": current_config,
                    "recommended_memory_mb": top_option.get("memorySize", 0),
                    "savings_pct": round(
                        savings_opportunity.get("savingsOpportunityPercentage", 0), 1
                    ),
                    "est_monthly_savings": round(est_monthly_savings, 2),
                    "lookback_period": rec.get("lookbackPeriodInDays", 0),
                    "num_invocations": rec.get("numberOfInvocations", 0),
                })

            total_savings = sum(r["est_monthly_savings"] for r in recommendations)
            return {
                "recommendations": recommendations,
                "total_monthly_savings": round(total_savings, 2),
                "count": len(recommendations),
            }
        except Exception as e:
            return {"recommendations": [], "total_monthly_savings": 0, "count": 0, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Auto Scaling Group Recommendations
    # ------------------------------------------------------------------ #
    def get_asg_recommendations(self):
        try:
            resp = self.co.get_auto_scaling_group_recommendations()
            recommendations = []
            for rec in resp.get("autoScalingGroupRecommendations", []):
                current_config = rec.get("currentConfiguration", {})
                finding = rec.get("finding", "")

                options = rec.get("recommendationOptions", [])
                top_option = options[0] if options else {}
                top_config = top_option.get("configuration", {})

                savings_opportunity = top_option.get("savingsOpportunity", {})
                est_monthly_savings = float(
                    savings_opportunity.get("estimatedMonthlySavings", {})
                    .get("value", 0)
                )

                asg_arn = rec.get("autoScalingGroupArn", "")
                asg_name = rec.get("autoScalingGroupName", asg_arn.split("/")[-1] if "/" in asg_arn else "")

                recommendations.append({
                    "asg_name": asg_name,
                    "account_id": rec.get("accountId", ""),
                    "finding": finding,
                    "current_type": current_config.get("instanceType", "N/A"),
                    "current_desired": current_config.get("desiredCapacity", 0),
                    "current_min": current_config.get("minSize", 0),
                    "current_max": current_config.get("maxSize", 0),
                    "recommended_type": top_config.get("instanceType", "N/A"),
                    "recommended_desired": top_config.get("desiredCapacity", 0),
                    "savings_pct": round(
                        savings_opportunity.get("savingsOpportunityPercentage", 0), 1
                    ),
                    "est_monthly_savings": round(est_monthly_savings, 2),
                })

            total_savings = sum(r["est_monthly_savings"] for r in recommendations)
            return {
                "recommendations": recommendations,
                "total_monthly_savings": round(total_savings, 2),
                "count": len(recommendations),
            }
        except Exception as e:
            return {"recommendations": [], "total_monthly_savings": 0, "count": 0, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  ECS Service Recommendations
    # ------------------------------------------------------------------ #
    def get_ecs_recommendations(self):
        try:
            resp = self.co.get_ecs_service_recommendations()
            recommendations = []
            for rec in resp.get("ecsServiceRecommendations", []):
                current_config = rec.get("currentServiceConfiguration", {})
                finding = rec.get("finding", "")

                options = rec.get("serviceRecommendationOptions", [])
                top_option = options[0] if options else {}

                savings_opportunity = top_option.get("savingsOpportunity", {})
                est_monthly_savings = float(
                    savings_opportunity.get("estimatedMonthlySavings", {})
                    .get("value", 0)
                )

                svc_arn = rec.get("serviceArn", "")

                recommendations.append({
                    "service_arn": svc_arn,
                    "account_id": rec.get("accountId", ""),
                    "finding": finding,
                    "finding_reasons": rec.get("findingReasonCodes", []),
                    "launch_type": rec.get("launchType", ""),
                    "current_cpu": current_config.get("cpu", 0),
                    "current_memory": current_config.get("memory", 0),
                    "current_task_definition": current_config.get("taskDefinitionArn", ""),
                    "savings_pct": round(
                        savings_opportunity.get("savingsOpportunityPercentage", 0), 1
                    ),
                    "est_monthly_savings": round(est_monthly_savings, 2),
                })

            total_savings = sum(r["est_monthly_savings"] for r in recommendations)
            return {
                "recommendations": recommendations,
                "total_monthly_savings": round(total_savings, 2),
                "count": len(recommendations),
            }
        except Exception as e:
            return {"recommendations": [], "total_monthly_savings": 0, "count": 0, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Combined Summary (for dashboard widget)
    # ------------------------------------------------------------------ #
    def get_optimization_summary(self):
        """Aggregate summary across all Compute Optimizer recommendation types."""
        ec2 = self.get_ec2_recommendations()
        ebs = self.get_ebs_recommendations()
        lam = self.get_lambda_recommendations()
        asg = self.get_asg_recommendations()
        ecs = self.get_ecs_recommendations()

        total_savings = (
            ec2.get("total_monthly_savings", 0)
            + ebs.get("total_monthly_savings", 0)
            + lam.get("total_monthly_savings", 0)
            + asg.get("total_monthly_savings", 0)
            + ecs.get("total_monthly_savings", 0)
        )

        return {
            "total_monthly_savings": round(total_savings, 2),
            "ec2": {
                "count": ec2.get("count", 0),
                "savings": ec2.get("total_monthly_savings", 0),
                "over_provisioned": ec2.get("over_provisioned", 0),
                "under_provisioned": ec2.get("under_provisioned", 0),
                "optimized": ec2.get("optimized", 0),
                "error": ec2.get("error"),
            },
            "ebs": {
                "count": ebs.get("count", 0),
                "savings": ebs.get("total_monthly_savings", 0),
                "error": ebs.get("error"),
            },
            "lambda": {
                "count": lam.get("count", 0),
                "savings": lam.get("total_monthly_savings", 0),
                "error": lam.get("error"),
            },
            "asg": {
                "count": asg.get("count", 0),
                "savings": asg.get("total_monthly_savings", 0),
                "error": asg.get("error"),
            },
            "ecs": {
                "count": ecs.get("count", 0),
                "savings": ecs.get("total_monthly_savings", 0),
                "error": ecs.get("error"),
            },
            "ec2_detail": ec2,
            "ebs_detail": ebs,
            "lambda_detail": lam,
            "asg_detail": asg,
            "ecs_detail": ecs,
        }
