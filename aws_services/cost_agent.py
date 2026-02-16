"""
AWS Cost Optimization Agent
An intelligent analysis engine that scans AWS resources, applies AWS Well-Architected
cost optimization best practices, and generates prioritized recommendations with
estimated savings. This acts as a virtual FinOps advisor.
"""

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from aws_services.account_manager import get_session


class CostOptimizationAgent:
    """
    Autonomous agent that inspects an AWS account and produces a comprehensive
    cost-optimization report.  It checks:

    1. Spending Trends & Anomalies
    2. Idle / Underutilized Resources
    3. Right-sizing Opportunities
    4. Reserved Instance & Savings Plan Coverage Gaps
    5. Storage Optimization (S3 lifecycle, EBS type, snapshots)
    6. Network Cost Waste (unused EIPs, NAT Gateway, data-transfer)
    7. Graviton / Spot Instance Opportunities
    8. Tagging & Governance Compliance
    9. Old-Gen Instance Migration
    10. Lambda Memory & Timeout Tuning
    """

    # AWS best-practice thresholds
    IDLE_CPU_THRESHOLD = 5.0       # % average over 7 days
    LOW_CPU_THRESHOLD = 20.0       # % – candidate for downsize
    IDLE_NETWORK_THRESHOLD = 1000  # bytes/sec – nearly zero traffic
    EBS_SNAPSHOT_AGE_DAYS = 90     # snapshots older than this
    OLD_GEN_PREFIXES = (
        "t2.", "m4.", "m3.", "c4.", "c3.", "r4.", "r3.", "i3.", "d2.",
    )
    GRAVITON_FAMILIES = ("t4g", "m6g", "m7g", "c6g", "c7g", "r6g", "r7g")
    SPOT_SUITABLE_TAGS = ("dev", "test", "staging", "batch", "ci")

    def __init__(self):
        pass

    @property
    def session(self):
        return get_session()

    # ================================================================== #
    #  PUBLIC: Run Full Analysis
    # ================================================================== #
    def run_full_analysis(self):
        """Execute every check and return a structured report."""
        report = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "categories": [],
            "summary": {
                "total_opportunities": 0,
                "total_estimated_monthly_savings": 0.0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "info": 0,
            },
        }

        checks = [
            self._check_spending_trends,
            self._check_idle_ec2,
            self._check_underutilised_ec2,
            self._check_old_generation_instances,
            self._check_graviton_opportunities,
            self._check_spot_opportunities,
            self._check_unattached_ebs,
            self._check_ebs_type_optimization,
            self._check_old_snapshots,
            self._check_unused_elastic_ips,
            self._check_idle_load_balancers,
            self._check_idle_rds,
            self._check_rds_multi_az_dev,
            self._check_s3_lifecycle,
            self._check_s3_intelligent_tiering,
            self._check_nat_gateway_cost,
            self._check_lambda_memory,
            self._check_dynamodb_capacity,
            self._check_savings_plan_coverage,
            self._check_reserved_instance_coverage,
            self._check_tagging_compliance,
            self._check_stopped_ec2_with_ebs,
        ]

        for check_fn in checks:
            try:
                cat = check_fn()
                if cat and cat.get("findings"):
                    report["categories"].append(cat)
                    for f in cat["findings"]:
                        report["summary"]["total_opportunities"] += 1
                        sev = f.get("severity", "info")
                        report["summary"][sev] = report["summary"].get(sev, 0) + 1
                        report["summary"]["total_estimated_monthly_savings"] += f.get(
                            "est_monthly_savings", 0
                        )
            except Exception:
                pass  # Agent is fault-tolerant; skip failing checks

        report["summary"]["total_estimated_monthly_savings"] = round(
            report["summary"]["total_estimated_monthly_savings"], 2
        )
        return report

    # ================================================================== #
    #  PRIVATE CHECKS
    # ================================================================== #

    # ---- 1. Spending Trends ----------------------------------------- #
    def _check_spending_trends(self):
        ce = self.session.client("ce")
        today = datetime.utcnow().date()
        findings = []

        # Month-over-month spike detection
        try:
            start = (today - relativedelta(months=3)).replace(day=1).isoformat()
            end = today.replace(day=1).isoformat()
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            months = [
                {
                    "month": r["TimePeriod"]["Start"][:7],
                    "cost": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2),
                }
                for r in resp["ResultsByTime"]
            ]
            if len(months) >= 2:
                latest = months[-1]
                prev = months[-2]
                if prev["cost"] > 0:
                    pct = round((latest["cost"] - prev["cost"]) / prev["cost"] * 100, 1)
                    if pct > 20:
                        findings.append({
                            "title": f"Spending increased {pct}% month-over-month",
                            "description": (
                                f"{prev['month']}: ${prev['cost']:,.2f} → "
                                f"{latest['month']}: ${latest['cost']:,.2f}. "
                                "Investigate the services driving the increase."
                            ),
                            "severity": "high" if pct > 50 else "medium",
                            "est_monthly_savings": 0,
                            "best_practice": "AWS Well-Architected Cost Optimization Pillar: Monitor and track cost trends proactively.",
                            "action": "Review Cost Explorer grouped by Service to find the source of the spike.",
                        })
        except Exception:
            pass

        return {
            "name": "Spending Trend Analysis",
            "icon": "bi-graph-up-arrow",
            "findings": findings,
        } if findings else None

    # ---- 2. Idle EC2 (CPU < 5%) ------------------------------------- #
    def _check_idle_ec2(self):
        ec2 = self.session.client("ec2")
        cw = self.session.client("cloudwatch")
        findings = []

        try:
            instances = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            for res in instances["Reservations"]:
                for inst in res["Instances"]:
                    iid = inst["InstanceId"]
                    itype = inst["InstanceType"]
                    name = self._tag(inst.get("Tags", []), "Name")
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
                        if stats["Datapoints"]:
                            avg = sum(d["Average"] for d in stats["Datapoints"]) / len(
                                stats["Datapoints"]
                            )
                            if avg < self.IDLE_CPU_THRESHOLD:
                                est = self._estimate_ec2_cost(itype)
                                findings.append({
                                    "title": f"Idle EC2: {iid} ({name or itype})",
                                    "description": (
                                        f"Instance {iid} ({itype}) has {avg:.1f}% avg CPU over 7 days. "
                                        "Consider terminating or stopping if unused."
                                    ),
                                    "severity": "high",
                                    "resource_id": iid,
                                    "est_monthly_savings": est,
                                    "best_practice": "Terminate or stop instances with < 5% CPU for 7+ days.",
                                    "action": "Stop or terminate this instance. Use Auto Scaling for variable workloads.",
                                })
                    except Exception:
                        pass
        except Exception:
            pass

        return {
            "name": "Idle EC2 Instances",
            "icon": "bi-pc-display",
            "findings": findings,
        } if findings else None

    # ---- 3. Under-utilised EC2 (CPU < 20%) --------------------------- #
    def _check_underutilised_ec2(self):
        ec2 = self.session.client("ec2")
        cw = self.session.client("cloudwatch")
        findings = []

        try:
            instances = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            for res in instances["Reservations"]:
                for inst in res["Instances"]:
                    iid = inst["InstanceId"]
                    itype = inst["InstanceType"]
                    name = self._tag(inst.get("Tags", []), "Name")
                    try:
                        stats = cw.get_metric_statistics(
                            Namespace="AWS/EC2",
                            MetricName="CPUUtilization",
                            Dimensions=[{"Name": "InstanceId", "Value": iid}],
                            StartTime=datetime.utcnow() - timedelta(days=14),
                            EndTime=datetime.utcnow(),
                            Period=86400,
                            Statistics=["Average", "Maximum"],
                        )
                        if stats["Datapoints"]:
                            avg = sum(d["Average"] for d in stats["Datapoints"]) / len(
                                stats["Datapoints"]
                            )
                            max_cpu = max(d["Maximum"] for d in stats["Datapoints"])
                            if self.IDLE_CPU_THRESHOLD <= avg < self.LOW_CPU_THRESHOLD and max_cpu < 40:
                                est = self._estimate_ec2_cost(itype) * 0.4
                                findings.append({
                                    "title": f"Underutilized EC2: {iid} ({name or itype})",
                                    "description": (
                                        f"Instance {iid} ({itype}) avg CPU {avg:.1f}%, max {max_cpu:.1f}% over 14d. "
                                        "Downsize to a smaller instance type."
                                    ),
                                    "severity": "medium",
                                    "resource_id": iid,
                                    "est_monthly_savings": round(est, 2),
                                    "best_practice": "Right-size instances to match actual demand: use Compute Optimizer or Cost Explorer Rightsizing.",
                                    "action": f"Consider downsizing {itype} to the next smaller size in the same family.",
                                })
                    except Exception:
                        pass
        except Exception:
            pass

        return {
            "name": "Underutilized EC2 (Right-Sizing)",
            "icon": "bi-arrows-collapse",
            "findings": findings,
        } if findings else None

    # ---- 4. Old Generation Instances --------------------------------- #
    def _check_old_generation_instances(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            instances = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            for res in instances["Reservations"]:
                for inst in res["Instances"]:
                    itype = inst["InstanceType"]
                    if itype.startswith(self.OLD_GEN_PREFIXES):
                        iid = inst["InstanceId"]
                        name = self._tag(inst.get("Tags", []), "Name")
                        est = self._estimate_ec2_cost(itype) * 0.25
                        findings.append({
                            "title": f"Old-gen instance: {iid} ({itype})",
                            "description": (
                                f"Instance {iid} runs on previous-generation {itype}. "
                                "Newer generations offer better price-performance."
                            ),
                            "severity": "medium",
                            "resource_id": iid,
                            "est_monthly_savings": round(est, 2),
                            "best_practice": "Migrate to current-gen instances (e.g., t3/m6i/c6i) for up to 40% better price-performance.",
                            "action": f"Migrate {itype} to an equivalent current-gen type.",
                        })
        except Exception:
            pass
        return {
            "name": "Old-Generation Instance Migration",
            "icon": "bi-arrow-repeat",
            "findings": findings,
        } if findings else None

    # ---- 5. Graviton Opportunities ----------------------------------- #
    def _check_graviton_opportunities(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            instances = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            for res in instances["Reservations"]:
                for inst in res["Instances"]:
                    itype = inst["InstanceType"]
                    arch = inst.get("Architecture", "")
                    if arch != "arm64" and not any(itype.startswith(f) for f in self.GRAVITON_FAMILIES):
                        family = itype.split(".")[0]
                        size = itype.split(".")[-1] if "." in itype else ""
                        # Only flag if there's a plausible Graviton equivalent
                        graviton_map = {
                            "t3": "t4g", "m5": "m6g", "m6i": "m7g",
                            "c5": "c6g", "c6i": "c7g", "r5": "r6g", "r6i": "r7g",
                        }
                        if family in graviton_map:
                            target = f"{graviton_map[family]}.{size}"
                            est = self._estimate_ec2_cost(itype) * 0.2
                            iid = inst["InstanceId"]
                            name = self._tag(inst.get("Tags", []), "Name")
                            findings.append({
                                "title": f"Graviton candidate: {iid} ({itype})",
                                "description": (
                                    f"Instance {iid} ({itype}) can be migrated to Graviton {target} "
                                    "for ~20% cost savings with equivalent or better performance."
                                ),
                                "severity": "medium",
                                "resource_id": iid,
                                "est_monthly_savings": round(est, 2),
                                "best_practice": "AWS Graviton processors deliver up to 20% lower cost for compatible workloads.",
                                "action": f"Test workload on {target} and migrate if compatible (Linux, containerized, or interpreted-language workloads).",
                            })
        except Exception:
            pass
        return {
            "name": "Graviton Migration Opportunities",
            "icon": "bi-cpu",
            "findings": findings,
        } if findings else None

    # ---- 6. Spot Instance Opportunities ------------------------------ #
    def _check_spot_opportunities(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            instances = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            for res in instances["Reservations"]:
                for inst in res["Instances"]:
                    if inst.get("InstanceLifecycle") == "spot":
                        continue  # already Spot
                    tags = inst.get("Tags", [])
                    name = self._tag(tags, "Name").lower()
                    env = self._tag(tags, "Environment").lower() or self._tag(tags, "Env").lower()
                    if any(kw in name or kw in env for kw in self.SPOT_SUITABLE_TAGS):
                        iid = inst["InstanceId"]
                        itype = inst["InstanceType"]
                        est = self._estimate_ec2_cost(itype) * 0.65
                        findings.append({
                            "title": f"Spot candidate: {iid} ({self._tag(tags, 'Name') or itype})",
                            "description": (
                                f"Instance {iid} appears to be a non-production workload (tagged '{env or name}'). "
                                "Spot instances offer up to 90% savings vs On-Demand."
                            ),
                            "severity": "low",
                            "resource_id": iid,
                            "est_monthly_savings": round(est, 2),
                            "best_practice": "Use Spot for fault-tolerant, non-production, or batch workloads to save up to 90%.",
                            "action": "Convert to Spot or use a mixed On-Demand + Spot Auto Scaling strategy.",
                        })
        except Exception:
            pass
        return {
            "name": "Spot Instance Opportunities",
            "icon": "bi-lightning-charge",
            "findings": findings,
        } if findings else None

    # ---- 7. Unattached EBS Volumes ----------------------------------- #
    def _check_unattached_ebs(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            vols = ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["available"]}])
            for v in vols["Volumes"]:
                vid = v["VolumeId"]
                size = v["Size"]
                vtype = v["VolumeType"]
                est = self._ebs_monthly_cost(vtype, size)
                findings.append({
                    "title": f"Unattached EBS: {vid} ({size} GB {vtype})",
                    "description": (
                        f"Volume {vid} ({size} GB, {vtype}) is not attached to any instance. "
                        "Snapshot and delete to stop charges."
                    ),
                    "severity": "high",
                    "resource_id": vid,
                    "est_monthly_savings": round(est, 2),
                    "best_practice": "Delete unattached EBS volumes; create snapshots first as backup.",
                    "action": "Create a snapshot, then delete the volume.",
                })
        except Exception:
            pass
        return {
            "name": "Unattached EBS Volumes",
            "icon": "bi-device-hdd",
            "findings": findings,
        } if findings else None

    # ---- 8. EBS Type Optimization (gp2 → gp3) ----------------------- #
    def _check_ebs_type_optimization(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            vols = ec2.describe_volumes(Filters=[{"Name": "volume-type", "Values": ["gp2"]}])
            for v in vols["Volumes"]:
                vid = v["VolumeId"]
                size = v["Size"]
                est = size * 0.02  # gp3 is ~20% cheaper than gp2
                findings.append({
                    "title": f"Migrate {vid} from gp2 → gp3",
                    "description": (
                        f"Volume {vid} ({size} GB) uses gp2. gp3 offers same performance "
                        "at 20% lower baseline cost with free 3000 IOPS / 125 MiB/s."
                    ),
                    "severity": "medium",
                    "resource_id": vid,
                    "est_monthly_savings": round(est, 2),
                    "best_practice": "Migrate gp2 volumes to gp3 for 20% savings (gp3 is the recommended default).",
                    "action": "Modify volume type from gp2 to gp3 via Console or CLI.",
                })
        except Exception:
            pass
        return {
            "name": "EBS gp2 → gp3 Migration",
            "icon": "bi-hdd-stack",
            "findings": findings,
        } if findings else None

    # ---- 9. Old Snapshots -------------------------------------------- #
    def _check_old_snapshots(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            # Only owned snapshots
            owner = self.session.client("sts").get_caller_identity()["Account"]
            snaps = ec2.describe_snapshots(OwnerIds=[owner])
            cutoff = datetime.utcnow() - timedelta(days=self.EBS_SNAPSHOT_AGE_DAYS)
            total_size = 0
            old_count = 0
            for s in snaps.get("Snapshots", []):
                if s["StartTime"].replace(tzinfo=None) < cutoff:
                    total_size += s.get("VolumeSize", 0)
                    old_count += 1
            if old_count > 0:
                est = total_size * 0.05  # ~$0.05/GB-month for snapshots
                findings.append({
                    "title": f"{old_count} EBS snapshots older than {self.EBS_SNAPSHOT_AGE_DAYS} days",
                    "description": (
                        f"Found {old_count} snapshots totalling {total_size} GB older than "
                        f"{self.EBS_SNAPSHOT_AGE_DAYS} days. Review if they are still needed."
                    ),
                    "severity": "medium",
                    "est_monthly_savings": round(est, 2),
                    "best_practice": "Implement lifecycle policies for EBS snapshots. Use DLM to automate retention.",
                    "action": "Use Data Lifecycle Manager to auto-delete old snapshots or review manually.",
                })
        except Exception:
            pass
        return {
            "name": "Old EBS Snapshots",
            "icon": "bi-clock-history",
            "findings": findings,
        } if findings else None

    # ---- 10. Unused Elastic IPs -------------------------------------- #
    def _check_unused_elastic_ips(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            eips = ec2.describe_addresses()
            for addr in eips["Addresses"]:
                if "InstanceId" not in addr and "NetworkInterfaceId" not in addr:
                    ip = addr.get("PublicIp", "N/A")
                    findings.append({
                        "title": f"Unused Elastic IP: {ip}",
                        "description": (
                            f"EIP {ip} is not associated with any instance or ENI. "
                            "AWS charges $3.65/month for unused EIPs."
                        ),
                        "severity": "high",
                        "resource_id": addr.get("AllocationId", ""),
                        "est_monthly_savings": 3.65,
                        "best_practice": "Release unused Elastic IPs to avoid idle charges ($0.005/hr).",
                        "action": "Release this Elastic IP if no longer needed.",
                    })
        except Exception:
            pass
        return {
            "name": "Unused Elastic IPs",
            "icon": "bi-globe",
            "findings": findings,
        } if findings else None

    # ---- 11. Idle Load Balancers ------------------------------------- #
    def _check_idle_load_balancers(self):
        elb = self.session.client("elbv2")
        cw = self.session.client("cloudwatch")
        findings = []
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
                        Dimensions=[{"Name": "LoadBalancer", "Value": arn_suffix}],
                        StartTime=datetime.utcnow() - timedelta(days=7),
                        EndTime=datetime.utcnow(),
                        Period=604800,
                        Statistics=["Sum"],
                    )
                    total = sum(d["Sum"] for d in stats["Datapoints"])
                    if total == 0:
                        findings.append({
                            "title": f"Idle Load Balancer: {name}",
                            "description": (
                                f"ALB '{name}' processed 0 requests in the last 7 days. "
                                "Delete if no longer needed (~$16/month)."
                            ),
                            "severity": "high",
                            "resource_id": arn,
                            "est_monthly_savings": 16.20,
                            "best_practice": "Delete idle ALBs/NLBs. Minimum charge applies even with no traffic.",
                            "action": "Delete this load balancer after confirming it's unused.",
                        })
                except Exception:
                    pass
        except Exception:
            pass
        return {
            "name": "Idle Load Balancers",
            "icon": "bi-diagram-3",
            "findings": findings,
        } if findings else None

    # ---- 12. Idle RDS ------------------------------------------------ #
    def _check_idle_rds(self):
        rds = self.session.client("rds")
        cw = self.session.client("cloudwatch")
        findings = []
        try:
            dbs = rds.describe_db_instances()
            for db in dbs["DBInstances"]:
                dbid = db["DBInstanceIdentifier"]
                db_class = db["DBInstanceClass"]
                try:
                    stats = cw.get_metric_statistics(
                        Namespace="AWS/RDS",
                        MetricName="DatabaseConnections",
                        Dimensions=[{"Name": "DBInstanceIdentifier", "Value": dbid}],
                        StartTime=datetime.utcnow() - timedelta(days=7),
                        EndTime=datetime.utcnow(),
                        Period=86400,
                        Statistics=["Maximum"],
                    )
                    if stats["Datapoints"]:
                        max_conn = max(d["Maximum"] for d in stats["Datapoints"])
                        if max_conn == 0:
                            findings.append({
                                "title": f"No connections: RDS {dbid}",
                                "description": (
                                    f"RDS instance {dbid} ({db_class}, {db['Engine']}) had "
                                    "0 connections for 7 days. Stop or delete if unused."
                                ),
                                "severity": "high",
                                "resource_id": dbid,
                                "est_monthly_savings": self._estimate_rds_cost(db_class),
                                "best_practice": "Stop or snapshot-and-delete RDS instances with no connections.",
                                "action": "Use RDS stop (up to 7 days) or create final snapshot and delete.",
                            })
                except Exception:
                    pass
        except Exception:
            pass
        return {
            "name": "Idle RDS Instances",
            "icon": "bi-database-x",
            "findings": findings,
        } if findings else None

    # ---- 13. RDS Multi-AZ in Dev ------------------------------------- #
    def _check_rds_multi_az_dev(self):
        rds = self.session.client("rds")
        findings = []
        try:
            dbs = rds.describe_db_instances()
            for db in dbs["DBInstances"]:
                if db.get("MultiAZ"):
                    tags = rds.list_tags_for_resource(
                        ResourceName=db["DBInstanceArn"]
                    ).get("TagList", [])
                    env = self._tag(tags, "Environment").lower() or self._tag(tags, "Env").lower()
                    name = db["DBInstanceIdentifier"].lower()
                    if any(kw in env or kw in name for kw in ("dev", "test", "staging")):
                        est = self._estimate_rds_cost(db["DBInstanceClass"]) * 0.5
                        findings.append({
                            "title": f"Multi-AZ in non-prod: {db['DBInstanceIdentifier']}",
                            "description": (
                                f"RDS {db['DBInstanceIdentifier']} has Multi-AZ enabled but "
                                f"appears non-production ('{env or name}'). Disable to save ~50%."
                            ),
                            "severity": "medium",
                            "resource_id": db["DBInstanceIdentifier"],
                            "est_monthly_savings": round(est, 2),
                            "best_practice": "Disable Multi-AZ for dev/test RDS instances to halve costs.",
                            "action": "Modify RDS instance to disable Multi-AZ deployment.",
                        })
        except Exception:
            pass
        return {
            "name": "RDS Multi-AZ in Non-Production",
            "icon": "bi-database-gear",
            "findings": findings,
        } if findings else None

    # ---- 14. S3 Lifecycle Policies ----------------------------------- #
    def _check_s3_lifecycle(self):
        s3 = self.session.client("s3")
        findings = []
        try:
            buckets = s3.list_buckets().get("Buckets", [])
            for b in buckets:
                bname = b["Name"]
                try:
                    s3.get_bucket_lifecycle_configuration(Bucket=bname)
                except s3.exceptions.ClientError as e:
                    if "NoSuchLifecycleConfiguration" in str(e):
                        findings.append({
                            "title": f"No lifecycle: s3://{bname}",
                            "description": (
                                f"Bucket '{bname}' has no lifecycle policy. Objects will "
                                "remain in S3 Standard forever, even if infrequently accessed."
                            ),
                            "severity": "low",
                            "resource_id": bname,
                            "est_monthly_savings": 0,
                            "best_practice": "Add lifecycle rules to transition old objects to IA / Glacier / Deep Archive.",
                            "action": "Create a lifecycle rule to transition objects > 30d to S3-IA, > 90d to Glacier.",
                        })
        except Exception:
            pass
        return {
            "name": "S3 Lifecycle Policies",
            "icon": "bi-bucket",
            "findings": findings,
        } if findings else None

    # ---- 15. S3 Intelligent-Tiering ---------------------------------- #
    def _check_s3_intelligent_tiering(self):
        s3 = self.session.client("s3")
        findings = []
        try:
            buckets = s3.list_buckets().get("Buckets", [])
            for b in buckets:
                bname = b["Name"]
                try:
                    it_configs = s3.list_bucket_intelligent_tiering_configurations(
                        Bucket=bname
                    ).get("IntelligentTieringConfigurationList", [])
                    if not it_configs:
                        findings.append({
                            "title": f"No Intelligent-Tiering: s3://{bname}",
                            "description": (
                                f"Bucket '{bname}' does not use S3 Intelligent-Tiering. "
                                "IT auto-moves objects to cheaper tiers based on access patterns."
                            ),
                            "severity": "low",
                            "resource_id": bname,
                            "est_monthly_savings": 0,
                            "best_practice": "Enable S3 Intelligent-Tiering for buckets with unpredictable access patterns.",
                            "action": "Enable Intelligent-Tiering configuration on this bucket.",
                        })
                except Exception:
                    pass
        except Exception:
            pass
        return {
            "name": "S3 Intelligent-Tiering",
            "icon": "bi-arrow-down-up",
            "findings": findings,
        } if findings else None

    # ---- 16. NAT Gateway Cost ---------------------------------------- #
    def _check_nat_gateway_cost(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            nats = ec2.describe_nat_gateways(
                Filters=[{"Name": "state", "Values": ["available"]}]
            )
            gateways = nats.get("NatGateways", [])
            if len(gateways) > 1:
                est = (len(gateways) - 1) * 32.40  # ~$0.045/hr per NAT GW
                findings.append({
                    "title": f"{len(gateways)} NAT Gateways detected",
                    "description": (
                        f"You have {len(gateways)} NAT Gateways. Each costs ~$32/month + data transfer. "
                        "Consolidate where possible or use VPC endpoints for AWS services."
                    ),
                    "severity": "medium",
                    "est_monthly_savings": round(est, 2),
                    "best_practice": "Use VPC Endpoints (Gateway type is free for S3/DynamoDB). Minimize NAT Gateway count.",
                    "action": "Add S3/DynamoDB VPC Gateway Endpoints and review if all NAT Gateways are needed.",
                })
        except Exception:
            pass
        return {
            "name": "NAT Gateway Optimization",
            "icon": "bi-router",
            "findings": findings,
        } if findings else None

    # ---- 17. Lambda Memory Tuning ------------------------------------ #
    def _check_lambda_memory(self):
        lam = self.session.client("lambda")
        findings = []
        try:
            funcs = lam.list_functions()
            for fn in funcs.get("Functions", []):
                mem = fn.get("MemorySize", 128)
                timeout = fn.get("Timeout", 3)
                name = fn.get("FunctionName", "")
                if mem >= 512 and timeout <= 10:
                    findings.append({
                        "title": f"Over-provisioned Lambda: {name}",
                        "description": (
                            f"Lambda '{name}' has {mem} MB memory but only {timeout}s timeout. "
                            "Review if memory can be reduced (Lambda pricing is proportional to memory)."
                        ),
                        "severity": "low",
                        "resource_id": name,
                        "est_monthly_savings": 0,
                        "best_practice": "Use AWS Lambda Power Tuning to find optimal memory setting.",
                        "action": "Run Lambda Power Tuning tool or Compute Optimizer Lambda analysis.",
                    })
                elif mem == 128 and timeout >= 60:
                    findings.append({
                        "title": f"Under-provisioned Lambda: {name}",
                        "description": (
                            f"Lambda '{name}' has minimal memory ({mem} MB) but long timeout ({timeout}s). "
                            "Increasing memory may reduce duration and total cost."
                        ),
                        "severity": "low",
                        "resource_id": name,
                        "est_monthly_savings": 0,
                        "best_practice": "Increasing Lambda memory also increases CPU, which can reduce duration and cost.",
                        "action": "Test with higher memory and measure if duration drops proportionally.",
                    })
        except Exception:
            pass
        return {
            "name": "Lambda Memory Tuning",
            "icon": "bi-lightning",
            "findings": findings,
        } if findings else None

    # ---- 18. DynamoDB Capacity Mode ---------------------------------- #
    def _check_dynamodb_capacity(self):
        ddb = self.session.client("dynamodb")
        findings = []
        try:
            tables = ddb.list_tables().get("TableNames", [])
            for tname in tables:
                desc = ddb.describe_table(TableName=tname)["Table"]
                mode = desc.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
                if mode == "PROVISIONED":
                    rcu = desc.get("ProvisionedThroughput", {}).get("ReadCapacityUnits", 0)
                    wcu = desc.get("ProvisionedThroughput", {}).get("WriteCapacityUnits", 0)
                    if rcu > 0 or wcu > 0:
                        findings.append({
                            "title": f"DynamoDB provisioned: {tname}",
                            "description": (
                                f"Table '{tname}' uses Provisioned mode ({rcu} RCU, {wcu} WCU). "
                                "Evaluate switching to On-Demand if traffic is unpredictable."
                            ),
                            "severity": "low",
                            "resource_id": tname,
                            "est_monthly_savings": 0,
                            "best_practice": "Use On-Demand for unpredictable workloads or provisioned + auto-scaling for steady ones.",
                            "action": "Review CloudWatch consumed vs provisioned capacity and choose optimal mode.",
                        })
        except Exception:
            pass
        return {
            "name": "DynamoDB Capacity Optimization",
            "icon": "bi-table",
            "findings": findings,
        } if findings else None

    # ---- 19. Savings Plan Coverage ----------------------------------- #
    def _check_savings_plan_coverage(self):
        ce = self.session.client("ce")
        findings = []
        try:
            today = datetime.utcnow().date()
            resp = ce.get_savings_plans_coverage(
                TimePeriod={
                    "Start": (today - timedelta(days=30)).isoformat(),
                    "End": today.isoformat(),
                },
                Granularity="MONTHLY",
            )
            for item in resp.get("SavingsPlansCoverages", []):
                cov = float(item.get("Coverage", {}).get("CoveragePercentage", "0"))
                od = float(item.get("Coverage", {}).get("OnDemandCost", "0"))
                if cov < 70 and od > 100:
                    est = od * 0.25  # typical SP savings
                    findings.append({
                        "title": f"Savings Plan coverage only {cov:.0f}%",
                        "description": (
                            f"Your Savings Plans cover only {cov:.0f}% of eligible spend. "
                            f"${od:,.2f} was charged at On-Demand rates last month. "
                            "Purchasing additional Savings Plans could save ~25%."
                        ),
                        "severity": "high",
                        "est_monthly_savings": round(est, 2),
                        "best_practice": "Maintain > 70% Savings Plan coverage for steady compute workloads.",
                        "action": "Use CE Savings Plans Recommendations to purchase additional plans.",
                    })
        except Exception:
            pass
        return {
            "name": "Savings Plan Coverage",
            "icon": "bi-piggy-bank",
            "findings": findings,
        } if findings else None

    # ---- 20. RI Coverage --------------------------------------------- #
    def _check_reserved_instance_coverage(self):
        ce = self.session.client("ce")
        findings = []
        try:
            today = datetime.utcnow().date()
            resp = ce.get_reservation_coverage(
                TimePeriod={
                    "Start": (today - timedelta(days=30)).isoformat(),
                    "End": today.isoformat(),
                },
                Granularity="MONTHLY",
            )
            for item in resp.get("CoveragesByTime", []):
                total_cov = item.get("Total", {}).get("CoverageHours", {})
                pct = float(total_cov.get("CoverageHoursPercentage", "0"))
                od_hours_cost = float(total_cov.get("OnDemandHours", "0"))
                if pct < 50 and od_hours_cost > 100:
                    findings.append({
                        "title": f"Reserved Instance coverage only {pct:.0f}%",
                        "description": (
                            f"RI coverage is {pct:.0f}%. Consider purchasing RIs for steady-state workloads "
                            "if Savings Plans are not preferred."
                        ),
                        "severity": "medium",
                        "est_monthly_savings": 0,
                        "best_practice": "Use RIs or Savings Plans to cover predictable, long-running workloads.",
                        "action": "Review RI Recommendations in Cost Explorer.",
                    })
        except Exception:
            pass
        return {
            "name": "Reserved Instance Coverage",
            "icon": "bi-tag",
            "findings": findings,
        } if findings else None

    # ---- 21. Tagging Compliance -------------------------------------- #
    def _check_tagging_compliance(self):
        ec2 = self.session.client("ec2")
        findings = []
        required_tags = {"Name", "Environment", "Owner", "Project"}
        try:
            instances = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            missing_count = 0
            for res in instances["Reservations"]:
                for inst in res["Instances"]:
                    tags = {t["Key"] for t in inst.get("Tags", [])}
                    missing = required_tags - tags
                    if missing:
                        missing_count += 1
            if missing_count > 0:
                findings.append({
                    "title": f"{missing_count} EC2 instances missing required tags",
                    "description": (
                        f"{missing_count} running instances are missing one or more of: "
                        f"{', '.join(sorted(required_tags))}. "
                        "Proper tagging is essential for cost allocation and governance."
                    ),
                    "severity": "medium",
                    "est_monthly_savings": 0,
                    "best_practice": "Enforce tagging via AWS Organizations SCPs or Tag Policies for accurate cost allocation.",
                    "action": "Use AWS Tag Editor to bulk-apply missing tags. Implement AWS Config rules.",
                })
        except Exception:
            pass
        return {
            "name": "Tagging Compliance",
            "icon": "bi-tags",
            "findings": findings,
        } if findings else None

    # ---- 22. Stopped EC2 still paying for EBS ------------------------ #
    def _check_stopped_ec2_with_ebs(self):
        ec2 = self.session.client("ec2")
        findings = []
        try:
            instances = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
            )
            for res in instances["Reservations"]:
                for inst in res["Instances"]:
                    iid = inst["InstanceId"]
                    name = self._tag(inst.get("Tags", []), "Name")
                    ebs_total_gb = sum(
                        bd.get("Ebs", {}).get("VolumeSize", 0)
                        for bd in inst.get("BlockDeviceMappings", [])
                    )
                    if ebs_total_gb > 0:
                        est = ebs_total_gb * 0.10  # ~$0.10/GB for gp2/gp3
                        findings.append({
                            "title": f"Stopped EC2 with EBS: {iid} ({name or 'unnamed'})",
                            "description": (
                                f"Instance {iid} is stopped but still paying for {ebs_total_gb} GB EBS storage. "
                                "Create an AMI and terminate if not needed."
                            ),
                            "severity": "medium",
                            "resource_id": iid,
                            "est_monthly_savings": round(est, 2),
                            "best_practice": "Create AMIs of stopped instances and terminate to avoid ongoing EBS charges.",
                            "action": "Create an AMI, then terminate the instance. Relaunch from AMI when needed.",
                        })
        except Exception:
            pass
        return {
            "name": "Stopped EC2 with EBS Charges",
            "icon": "bi-stop-circle",
            "findings": findings,
        } if findings else None

    # ================================================================== #
    #  HELPERS
    # ================================================================== #
    @staticmethod
    def _tag(tags, key):
        for t in tags or []:
            if t.get("Key") == key:
                return t.get("Value", "")
        return ""

    @staticmethod
    def _estimate_ec2_cost(instance_type):
        """Rough monthly estimate based on instance family/size."""
        size_map = {
            "nano": 4, "micro": 8, "small": 17, "medium": 34,
            "large": 68, "xlarge": 135, "2xlarge": 270, "4xlarge": 540,
            "8xlarge": 1080, "12xlarge": 1620, "16xlarge": 2160,
            "24xlarge": 3240, "metal": 4000,
        }
        parts = instance_type.split(".")
        size = parts[-1] if len(parts) > 1 else "large"
        return size_map.get(size, 68)

    @staticmethod
    def _estimate_rds_cost(db_class):
        """Rough monthly RDS cost estimate."""
        size_map = {
            "micro": 15, "small": 30, "medium": 65, "large": 130,
            "xlarge": 260, "2xlarge": 520, "4xlarge": 1040,
            "8xlarge": 2080, "12xlarge": 3120, "16xlarge": 4160,
        }
        parts = db_class.replace("db.", "").split(".")
        size = parts[-1] if parts else "large"
        return size_map.get(size, 130)

    @staticmethod
    def _ebs_monthly_cost(vol_type, size_gb):
        """Rough monthly EBS cost."""
        rates = {"gp2": 0.10, "gp3": 0.08, "io1": 0.125, "io2": 0.125,
                 "st1": 0.045, "sc1": 0.015, "standard": 0.05}
        return size_gb * rates.get(vol_type, 0.10)
