"""
AWS Savings Plans & Reserved Instances Service
Provides savings-plan / RI inventory, coverage, utilization, and recommendations.
"""

from datetime import datetime, timedelta
from aws_services.account_manager import get_session


class SavingsPlansService:
    def __init__(self):
        pass

    @property
    def session(self):
        return get_session()

    @property
    def ce(self):
        return self.session.client("ce")

    # ------------------------------------------------------------------ #
    #  Active Savings Plans
    # ------------------------------------------------------------------ #
    def get_savings_plans(self):
        try:
            sp_client = self.session.client("savingsplans")
            resp = sp_client.describe_savings_plans()
            plans = []
            for sp in resp.get("savingsPlans", []):
                plans.append({
                    "id": sp.get("savingsPlanId", ""),
                    "type": sp.get("savingsPlanType", ""),
                    "state": sp.get("state", ""),
                    "payment_option": sp.get("paymentOption", ""),
                    "offering_type": sp.get("offeringType", ""),
                    "commitment_per_hour": sp.get("commitment", "0"),
                    "start": sp.get("start", ""),
                    "end": sp.get("end", ""),
                    "region": sp.get("region", ""),
                    "upfront_payment": sp.get("upfrontPaymentAmount", "0"),
                    "recurring_payment": sp.get("recurringPaymentAmount", "0"),
                })
            return plans
        except Exception as e:
            return [{"error": str(e)}]

    # ------------------------------------------------------------------ #
    #  Reserved Instances
    # ------------------------------------------------------------------ #
    def get_reserved_instances(self):
        try:
            ec2 = self.session.client("ec2")
            resp = ec2.describe_reserved_instances(
                Filters=[{"Name": "state", "Values": ["active"]}]
            )
            instances = []
            for ri in resp.get("ReservedInstances", []):
                instances.append({
                    "id": ri["ReservedInstancesId"],
                    "type": ri["InstanceType"],
                    "count": ri["InstanceCount"],
                    "state": ri["State"],
                    "offering_type": ri.get("OfferingType", ""),
                    "offering_class": ri.get("OfferingClass", ""),
                    "scope": ri.get("Scope", ""),
                    "start": ri.get("Start", "").isoformat()
                        if ri.get("Start") else "",
                    "end": ri.get("End", "").isoformat()
                        if ri.get("End") else "",
                    "duration_seconds": ri.get("Duration", 0),
                    "fixed_price": round(float(ri.get("FixedPrice", 0)), 2),
                    "usage_price": round(float(ri.get("UsagePrice", 0)), 6),
                })

            # Also grab RDS reserved instances
            try:
                rds = self.session.client("rds")
                rds_resp = rds.describe_reserved_db_instances()
                for ri in rds_resp.get("ReservedDBInstances", []):
                    instances.append({
                        "id": ri["ReservedDBInstanceId"],
                        "type": ri["DBInstanceClass"],
                        "count": ri["DBInstanceCount"],
                        "state": ri["State"],
                        "offering_type": ri.get("OfferingType", ""),
                        "offering_class": "RDS",
                        "scope": ri.get("ProductDescription", ""),
                        "start": ri.get("StartTime", "").isoformat()
                            if ri.get("StartTime") else "",
                        "end": "",
                        "duration_seconds": ri.get("Duration", 0),
                        "fixed_price": round(float(ri.get("FixedPrice", 0)), 2),
                        "usage_price": round(float(ri.get("UsagePrice", 0)), 6),
                    })
            except Exception:
                pass

            return instances
        except Exception as e:
            return [{"error": str(e)}]

    # ------------------------------------------------------------------ #
    #  Savings Plan Coverage (last 30 days)
    # ------------------------------------------------------------------ #
    def get_savings_plan_coverage(self):
        try:
            today = datetime.utcnow().date()
            start = (today - timedelta(days=30)).isoformat()
            end = today.isoformat()

            resp = self.ce.get_savings_plans_coverage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
            )
            results = []
            for item in resp.get("SavingsPlansCoverages", []):
                coverage = item.get("Coverage", {})
                results.append({
                    "period_start": item.get("TimePeriod", {}).get("Start", ""),
                    "period_end": item.get("TimePeriod", {}).get("End", ""),
                    "coverage_pct": coverage.get("CoveragePercentage", "0"),
                    "spend_covered": coverage.get("SpendCoveredBySavingsPlans", "0"),
                    "on_demand_cost": coverage.get("OnDemandCost", "0"),
                    "total_cost": coverage.get("TotalCost", "0"),
                })
            return results
        except Exception as e:
            return [{"error": str(e)}]

    # ------------------------------------------------------------------ #
    #  Savings Plan Utilization (last 30 days)
    # ------------------------------------------------------------------ #
    def get_savings_plan_utilization(self):
        try:
            today = datetime.utcnow().date()
            start = (today - timedelta(days=30)).isoformat()
            end = today.isoformat()

            resp = self.ce.get_savings_plans_utilization(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
            )
            total = resp.get("Total", {})
            return {
                "utilization_pct": total.get("Utilization", {})
                    .get("UtilizationPercentage", "0"),
                "total_commitment": total.get("Utilization", {})
                    .get("TotalCommitment", "0"),
                "used_commitment": total.get("Utilization", {})
                    .get("UsedCommitment", "0"),
                "unused_commitment": total.get("Utilization", {})
                    .get("UnusedCommitment", "0"),
                "net_savings": total.get("Savings", {})
                    .get("NetSavings", "0"),
                "on_demand_equivalent": total.get("Savings", {})
                    .get("OnDemandCostEquivalent", "0"),
                "periods": [
                    {
                        "start": p.get("TimePeriod", {}).get("Start", ""),
                        "end": p.get("TimePeriod", {}).get("End", ""),
                        "utilization_pct": p.get("Utilization", {})
                            .get("UtilizationPercentage", "0"),
                    }
                    for p in resp.get("SavingsPlansUtilizationsByTime", [])
                ],
            }
        except Exception as e:
            return {"utilization_pct": "0", "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Savings Plan Purchase Recommendations
    # ------------------------------------------------------------------ #
    def get_savings_plan_recommendations(self):
        try:
            resp = self.ce.get_savings_plans_purchase_recommendation(
                SavingsPlansType="COMPUTE_SP",
                TermInYears="ONE_YEAR",
                PaymentOption="NO_UPFRONT",
                LookbackPeriodInDays="THIRTY_DAYS",
            )
            meta = resp.get("SavingsPlansPurchaseRecommendation", {})
            details = meta.get("SavingsPlansPurchaseRecommendationDetails", [])

            recommendations = []
            for d in details:
                recommendations.append({
                    "hourly_commitment": d.get("HourlyCommitmentToPurchase", "0"),
                    "estimated_monthly_savings": d.get("EstimatedMonthlySavingsAmount", "0"),
                    "estimated_savings_pct": d.get("EstimatedSavingsPercentage", "0"),
                    "estimated_on_demand_cost": d.get("EstimatedOnDemandCost", "0"),
                    "estimated_sp_cost": d.get("EstimatedSPCost", "0"),
                    "upfront_cost": d.get("UpfrontCost", "0"),
                    "current_avg_hourly_od": d.get("CurrentAverageHourlyOnDemandSpend", "0"),
                })

            summary = meta.get("SavingsPlansPurchaseRecommendationSummary", {})
            return {
                "recommendations": recommendations,
                "estimated_total_savings": summary.get(
                    "EstimatedTotalSavings", {}).get("Amount", "0")
                    if isinstance(summary.get("EstimatedTotalSavings"), dict)
                    else summary.get("EstimatedMonthlySavingsAmount", "0"),
                "currency": "USD",
            }
        except Exception as e:
            return {"recommendations": [], "error": str(e)}
