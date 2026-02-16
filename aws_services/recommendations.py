"""
AWS Recommendation Service
Provides rightsizing, Trusted Advisor, and idle-resource recommendations.
"""

from aws_services.account_manager import get_session


class RecommendationService:
    def __init__(self):
        pass

    @property
    def session(self):
        return get_session()

    @property
    def ce(self):
        return self.session.client("ce")

    # ------------------------------------------------------------------ #
    #  EC2 Rightsizing Recommendations
    # ------------------------------------------------------------------ #
    def get_rightsizing_recommendations(self):
        try:
            resp = self.ce.get_rightsizing_recommendation(
                Service="AmazonEC2",
                Configuration={
                    "RecommendationTarget": "SAME_INSTANCE_FAMILY",
                    "BenefitsConsidered": True,
                },
            )
            recommendations = []
            for rec in resp.get("RightsizingRecommendations", []):
                current = rec.get("CurrentInstance", {})
                modify = rec.get("ModifyRecommendationDetail", {})
                target = modify.get("TargetInstances", [{}])[0] if modify else {}

                monthly_savings = float(
                    rec.get("ModifyRecommendationDetail", {})
                    .get("TargetInstances", [{}])[0]
                    .get("EstimatedMonthlySavings", {})
                    .get("Value", 0)
                ) if modify and modify.get("TargetInstances") else 0

                recommendations.append({
                    "account_id": rec.get("AccountId", ""),
                    "instance_id": current.get("ResourceId", ""),
                    "instance_name": self._get_tag_value(
                        current.get("Tags", []), "Name"
                    ),
                    "current_type": current.get("ResourceDetails", {})
                        .get("EC2ResourceDetails", {})
                        .get("InstanceType", "N/A"),
                    "recommended_type": target.get("ResourceDetails", {})
                        .get("EC2ResourceDetails", {})
                        .get("InstanceType", "N/A"),
                    "recommendation_type": rec.get("RightsizingType", ""),
                    "monthly_savings": round(monthly_savings, 2),
                    "current_monthly_cost": round(
                        float(current.get("MonthlyCost", 0)), 2
                    ),
                    "cpu_max": current.get("ResourceUtilization", {})
                        .get("EC2ResourceUtilization", {})
                        .get("MaxCpuUtilizationPercentage", "N/A"),
                    "memory_max": current.get("ResourceUtilization", {})
                        .get("EC2ResourceUtilization", {})
                        .get("MaxMemoryUtilizationPercentage", "N/A"),
                })
            return {
                "recommendations": recommendations,
                "total_savings": round(
                    sum(r["monthly_savings"] for r in recommendations), 2
                ),
                "count": len(recommendations),
            }
        except Exception as e:
            return {"recommendations": [], "total_savings": 0, "count": 0, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Trusted Advisor Cost-Optimization Checks
    # ------------------------------------------------------------------ #
    def get_trusted_advisor_checks(self):
        try:
            support = self.session.client("support", region_name="us-east-1")
            resp = support.describe_trusted_advisor_checks(language="en")

            cost_checks = [
                c for c in resp["checks"] if c["category"] == "cost_optimizing"
            ]

            results = []
            for check in cost_checks:
                try:
                    detail = support.describe_trusted_advisor_check_result(
                        checkId=check["id"], language="en"
                    )
                    result = detail.get("result", {})
                    status = result.get("status", "not_available")
                    flagged = len(result.get("flaggedResources", []))
                    estimated_savings = 0.0

                    for fr in result.get("flaggedResources", []):
                        meta = fr.get("metadata", [])
                        # Last metadata field is often the estimated savings
                        for m in reversed(meta):
                            try:
                                estimated_savings += float(m.replace("$", "").replace(",", ""))
                                break
                            except (ValueError, AttributeError):
                                continue

                    results.append({
                        "id": check["id"],
                        "name": check["name"],
                        "description": check.get("description", ""),
                        "status": status,
                        "flagged_resources": flagged,
                        "estimated_savings": round(estimated_savings, 2),
                    })
                except Exception:
                    results.append({
                        "id": check["id"],
                        "name": check["name"],
                        "description": check.get("description", ""),
                        "status": "error",
                        "flagged_resources": 0,
                        "estimated_savings": 0,
                    })

            return results
        except Exception as e:
            return [{"error": str(e)}]

    # ------------------------------------------------------------------ #
    #  Idle / Under-utilised Resources
    # ------------------------------------------------------------------ #
    def get_idle_resources(self):
        idle = {"ec2": [], "ebs": [], "elb": [], "eip": [], "rds": []}
        ec2 = self.session.client("ec2")
        cw = self.session.client("cloudwatch")
        rds = self.session.client("rds")
        elb = self.session.client("elbv2")
        from datetime import datetime, timedelta

        # --- Idle EC2 (avg CPU < 5% over 7 days) ---
        try:
            instances = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            for res in instances["Reservations"]:
                for inst in res["Instances"]:
                    iid = inst["InstanceId"]
                    try:
                        stats = cw.get_metric_statistics(
                            Namespace="AWS/EC2",
                            MetricName="CPUUtilization",
                            Dimensions=[{"Name": "InstanceId", "Value": iid}],
                            StartTime=datetime.utcnow() - timedelta(days=7),
                            EndTime=datetime.utcnow(),
                            Period=86400,
                            Statistics=["Average"],
                        )
                        avg = (
                            sum(d["Average"] for d in stats["Datapoints"])
                            / len(stats["Datapoints"])
                            if stats["Datapoints"]
                            else None
                        )
                        if avg is not None and avg < 5:
                            idle["ec2"].append({
                                "id": iid,
                                "type": inst["InstanceType"],
                                "name": self._get_tag_value(
                                    inst.get("Tags", []), "Name"
                                ),
                                "avg_cpu": round(avg, 2),
                            })
                    except Exception:
                        pass
        except Exception:
            pass

        # --- Unattached EBS Volumes ---
        try:
            vols = ec2.describe_volumes(
                Filters=[{"Name": "status", "Values": ["available"]}]
            )
            for v in vols["Volumes"]:
                idle["ebs"].append({
                    "id": v["VolumeId"],
                    "size_gb": v["Size"],
                    "type": v["VolumeType"],
                    "created": v["CreateTime"].isoformat(),
                })
        except Exception:
            pass

        # --- Unused Elastic IPs ---
        try:
            eips = ec2.describe_addresses()
            for addr in eips["Addresses"]:
                if "InstanceId" not in addr and "NetworkInterfaceId" not in addr:
                    idle["eip"].append({
                        "public_ip": addr.get("PublicIp", ""),
                        "allocation_id": addr.get("AllocationId", ""),
                    })
        except Exception:
            pass

        # --- Idle RDS (avg CPU < 5% over 7 days) ---
        try:
            dbs = rds.describe_db_instances()
            for db in dbs["DBInstances"]:
                dbid = db["DBInstanceIdentifier"]
                try:
                    stats = cw.get_metric_statistics(
                        Namespace="AWS/RDS",
                        MetricName="CPUUtilization",
                        Dimensions=[{"Name": "DBInstanceIdentifier", "Value": dbid}],
                        StartTime=datetime.utcnow() - timedelta(days=7),
                        EndTime=datetime.utcnow(),
                        Period=86400,
                        Statistics=["Average"],
                    )
                    avg = (
                        sum(d["Average"] for d in stats["Datapoints"])
                        / len(stats["Datapoints"])
                        if stats["Datapoints"]
                        else None
                    )
                    if avg is not None and avg < 5:
                        idle["rds"].append({
                            "id": dbid,
                            "class": db["DBInstanceClass"],
                            "engine": db["Engine"],
                            "avg_cpu": round(avg, 2),
                        })
                except Exception:
                    pass
        except Exception:
            pass

        # --- Idle Load Balancers (0 requests last 7d) ---
        try:
            lbs = elb.describe_load_balancers()
            for lb in lbs["LoadBalancers"]:
                arn = lb["LoadBalancerArn"]
                name = lb["LoadBalancerName"]
                try:
                    arn_suffix = "/".join(arn.split("/")[-3:])
                    stats = cw.get_metric_statistics(
                        Namespace="AWS/ApplicationELB",
                        MetricName="RequestCount",
                        Dimensions=[
                            {"Name": "LoadBalancer", "Value": arn_suffix}
                        ],
                        StartTime=datetime.utcnow() - timedelta(days=7),
                        EndTime=datetime.utcnow(),
                        Period=604800,
                        Statistics=["Sum"],
                    )
                    total = sum(d["Sum"] for d in stats["Datapoints"])
                    if total == 0:
                        idle["elb"].append({
                            "name": name,
                            "arn": arn,
                            "type": lb["Type"],
                        })
                except Exception:
                    pass
        except Exception:
            pass

        return idle

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _get_tag_value(tags, key):
        for t in tags or []:
            if t.get("Key") == key:
                return t.get("Value", "")
        return ""
