"""
AWS Resource Inventory Service
Gathers inventory of EC2, RDS, S3, Lambda, EBS, VPC, and more.
"""

from aws_services.account_manager import get_session


class InventoryService:
    def __init__(self):
        pass

    @property
    def session(self):
        return get_session()

    def get_all_resources(self):
        """Return a dict keyed by service name with lists of resources."""
        return {
            "ec2_instances": self._get_ec2_instances(),
            "rds_instances": self._get_rds_instances(),
            "rds_reserved": self._get_rds_reserved_instances(),
            "savings_plans": self._get_savings_plans(),
            "s3_buckets": self._get_s3_buckets(),
            "lambda_functions": self._get_lambda_functions(),
            "ebs_volumes": self._get_ebs_volumes(),
            "elastic_ips": self._get_elastic_ips(),
            "load_balancers": self._get_load_balancers(),
            "vpcs": self._get_vpcs(),
            "dynamodb_tables": self._get_dynamodb_tables(),
            "ecs_clusters": self._get_ecs_clusters(),
        }

    # ---------- EC2 ---------- #
    def _get_ec2_instances(self):
        try:
            ec2 = self.session.client("ec2")
            resp = ec2.describe_instances()
            instances = []
            for res in resp["Reservations"]:
                for inst in res["Instances"]:
                    instances.append({
                        "id": inst["InstanceId"],
                        "type": inst["InstanceType"],
                        "state": inst["State"]["Name"],
                        "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
                        "private_ip": inst.get("PrivateIpAddress", ""),
                        "public_ip": inst.get("PublicIpAddress", ""),
                        "name": self._tag(inst.get("Tags", []), "Name"),
                        "launch_time": inst.get("LaunchTime", "").isoformat()
                            if inst.get("LaunchTime") else "",
                        "platform": inst.get("PlatformDetails", "Linux/UNIX"),
                    })
            return instances
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- RDS ---------- #
    def _get_rds_instances(self):
        try:
            rds = self.session.client("rds")
            resp = rds.describe_db_instances()
            return [
                {
                    "id": db["DBInstanceIdentifier"],
                    "engine": db["Engine"],
                    "version": db.get("EngineVersion", ""),
                    "class": db["DBInstanceClass"],
                    "status": db["DBInstanceStatus"],
                    "storage_gb": db.get("AllocatedStorage", 0),
                    "multi_az": db.get("MultiAZ", False),
                    "endpoint": db.get("Endpoint", {}).get("Address", ""),
                }
                for db in resp["DBInstances"]
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- S3 ---------- #
    def _get_s3_buckets(self):
        try:
            s3 = self.session.client("s3")
            resp = s3.list_buckets()
            buckets = []
            for b in resp.get("Buckets", []):
                name = b["Name"]
                created = b.get("CreationDate", "")

                # Try to get region
                region = "unknown"
                try:
                    loc = s3.get_bucket_location(Bucket=name)
                    region = loc.get("LocationConstraint") or "us-east-1"
                except Exception:
                    pass

                # Try to get versioning
                versioning = "Disabled"
                try:
                    v_resp = s3.get_bucket_versioning(Bucket=name)
                    versioning = v_resp.get("Status", "Disabled")
                except Exception:
                    pass

                # Try to get encryption
                encryption = "None"
                try:
                    enc_resp = s3.get_bucket_encryption(Bucket=name)
                    rules = enc_resp.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
                    if rules:
                        encryption = rules[0].get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm", "None")
                except Exception:
                    pass

                # Try to get bucket size & object count from CloudWatch
                size_bytes = 0
                object_count = 0
                try:
                    from datetime import datetime, timedelta
                    cw = self.session.client("cloudwatch", region_name=region if region != "unknown" else "us-east-1")
                    end_time = datetime.utcnow()
                    start_time = end_time - timedelta(days=3)
                    size_resp = cw.get_metric_statistics(
                        Namespace="AWS/S3",
                        MetricName="BucketSizeBytes",
                        Dimensions=[
                            {"Name": "BucketName", "Value": name},
                            {"Name": "StorageType", "Value": "StandardStorage"},
                        ],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=86400,
                        Statistics=["Average"],
                    )
                    if size_resp.get("Datapoints"):
                        # Sort by Timestamp and take the latest
                        dp = sorted(size_resp["Datapoints"], key=lambda x: x["Timestamp"])
                        size_bytes = dp[-1].get("Average", 0)

                    count_resp = cw.get_metric_statistics(
                        Namespace="AWS/S3",
                        MetricName="NumberOfObjects",
                        Dimensions=[
                            {"Name": "BucketName", "Value": name},
                            {"Name": "StorageType", "Value": "AllStorageTypes"},
                        ],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=86400,
                        Statistics=["Average"],
                    )
                    if count_resp.get("Datapoints"):
                        dp = sorted(count_resp["Datapoints"], key=lambda x: x["Timestamp"])
                        object_count = int(dp[-1].get("Average", 0))
                except Exception:
                    pass

                buckets.append({
                    "name": name,
                    "region": region,
                    "created": created.isoformat() if created else "",
                    "size_bytes": size_bytes,
                    "object_count": object_count,
                    "versioning": versioning,
                    "encryption": encryption,
                })
            return buckets
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- Lambda ---------- #
    def _get_lambda_functions(self):
        try:
            lam = self.session.client("lambda")
            functions = []
            params = {"MaxItems": 50}
            while True:
                resp = lam.list_functions(**params)
                for fn in resp.get("Functions", []):
                    func_name = fn["FunctionName"]
                    description = fn.get("Description", "")
                    handler = fn.get("Handler", "N/A")
                    arch = ", ".join(fn.get("Architectures", ["x86_64"]))
                    layers_count = len(fn.get("Layers", []))
                    env_vars_count = len(fn.get("Environment", {}).get("Variables", {}))

                    functions.append({
                        "name": func_name,
                        "description": description,
                        "runtime": fn.get("Runtime", "N/A"),
                        "handler": handler,
                        "memory_mb": fn.get("MemorySize", 0),
                        "timeout": fn.get("Timeout", 0),
                        "last_modified": fn.get("LastModified", ""),
                        "code_size_bytes": fn.get("CodeSize", 0),
                        "architecture": arch,
                        "layers_count": layers_count,
                        "env_vars_count": env_vars_count,
                    })
                marker = resp.get("NextMarker")
                if not marker:
                    break
                params["Marker"] = marker
            return functions
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- RDS Reserved Instances ---------- #
    def _get_rds_reserved_instances(self):
        try:
            rds = self.session.client("rds")
            resp = rds.describe_reserved_db_instances()
            return [
                {
                    "id": ri["ReservedDBInstanceId"],
                    "class": ri["DBInstanceClass"],
                    "engine": ri.get("ProductDescription", ""),
                    "count": ri["DBInstanceCount"],
                    "state": ri["State"],
                    "offering_type": ri.get("OfferingType", ""),
                    "multi_az": ri.get("MultiAZ", False),
                    "start_time": ri.get("StartTime", "").isoformat()
                        if ri.get("StartTime") else "",
                    "duration_seconds": ri.get("Duration", 0),
                    "fixed_price": round(float(ri.get("FixedPrice", 0)), 2),
                    "recurring_charges": round(
                        sum(float(rc.get("RecurringChargeAmount", 0))
                            for rc in ri.get("RecurringCharges", [])), 4
                    ),
                }
                for ri in resp.get("ReservedDBInstances", [])
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- Savings Plans ---------- #
    def _get_savings_plans(self):
        try:
            sp = self.session.client("savingsplans")
            resp = sp.describe_savings_plans()
            return [
                {
                    "id": plan.get("savingsPlanId", ""),
                    "type": plan.get("savingsPlanType", ""),
                    "state": plan.get("state", ""),
                    "payment_option": plan.get("paymentOption", ""),
                    "commitment_per_hour": plan.get("commitment", "0"),
                    "start": plan.get("start", ""),
                    "end": plan.get("end", ""),
                    "region": plan.get("region", ""),
                    "upfront_payment": plan.get("upfrontPaymentAmount", "0"),
                    "recurring_payment": plan.get("recurringPaymentAmount", "0"),
                    "currency": plan.get("currency", "USD"),
                    "term_duration": plan.get("termDurationInSeconds", 0),
                }
                for plan in resp.get("savingsPlans", [])
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- EBS ---------- #
    def _get_ebs_volumes(self):
        try:
            ec2 = self.session.client("ec2")
            resp = ec2.describe_volumes()
            return [
                {
                    "id": v["VolumeId"],
                    "size_gb": v["Size"],
                    "type": v["VolumeType"],
                    "state": v["State"],
                    "az": v["AvailabilityZone"],
                    "iops": v.get("Iops", "N/A"),
                    "encrypted": v.get("Encrypted", False),
                    "attached_to": v["Attachments"][0]["InstanceId"]
                        if v.get("Attachments") else "Unattached",
                    "name": self._tag(v.get("Tags", []), "Name"),
                }
                for v in resp["Volumes"]
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- Elastic IPs ---------- #
    def _get_elastic_ips(self):
        try:
            ec2 = self.session.client("ec2")
            resp = ec2.describe_addresses()
            return [
                {
                    "public_ip": addr.get("PublicIp", ""),
                    "allocation_id": addr.get("AllocationId", ""),
                    "associated_instance": addr.get("InstanceId", "Unassociated"),
                    "domain": addr.get("Domain", ""),
                }
                for addr in resp["Addresses"]
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- Load Balancers ---------- #
    def _get_load_balancers(self):
        try:
            elb = self.session.client("elbv2")
            resp = elb.describe_load_balancers()
            return [
                {
                    "name": lb["LoadBalancerName"],
                    "type": lb["Type"],
                    "scheme": lb["Scheme"],
                    "state": lb["State"]["Code"],
                    "dns": lb["DNSName"],
                    "az": ", ".join(az["ZoneName"] for az in lb.get("AvailabilityZones", [])),
                }
                for lb in resp["LoadBalancers"]
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- VPCs ---------- #
    def _get_vpcs(self):
        try:
            ec2 = self.session.client("ec2")
            resp = ec2.describe_vpcs()
            return [
                {
                    "id": vpc["VpcId"],
                    "cidr": vpc["CidrBlock"],
                    "state": vpc["State"],
                    "is_default": vpc.get("IsDefault", False),
                    "name": self._tag(vpc.get("Tags", []), "Name"),
                }
                for vpc in resp["Vpcs"]
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- DynamoDB ---------- #
    def _get_dynamodb_tables(self):
        try:
            ddb = self.session.client("dynamodb")
            tables = ddb.list_tables().get("TableNames", [])
            result = []
            for tname in tables:
                try:
                    desc = ddb.describe_table(TableName=tname)["Table"]
                    result.append({
                        "name": tname,
                        "status": desc["TableStatus"],
                        "item_count": desc.get("ItemCount", 0),
                        "size_bytes": desc.get("TableSizeBytes", 0),
                        "billing_mode": desc.get("BillingModeSummary", {})
                            .get("BillingMode", "PROVISIONED"),
                    })
                except Exception:
                    result.append({"name": tname, "status": "error"})
            return result
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- ECS ---------- #
    def _get_ecs_clusters(self):
        try:
            ecs = self.session.client("ecs")
            arns = ecs.list_clusters().get("clusterArns", [])
            if not arns:
                return []
            details = ecs.describe_clusters(clusters=arns)
            return [
                {
                    "name": c["clusterName"],
                    "status": c["status"],
                    "running_tasks": c.get("runningTasksCount", 0),
                    "active_services": c.get("activeServicesCount", 0),
                    "registered_instances": c.get("registeredContainerInstancesCount", 0),
                }
                for c in details["clusters"]
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---------- Helpers ---------- #
    @staticmethod
    def _tag(tags, key):
        for t in tags or []:
            if t.get("Key") == key:
                return t.get("Value", "")
        return ""
