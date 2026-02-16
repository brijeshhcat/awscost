"""
AWS Cost Explorer Service
Handles cost data retrieval, analysis, forecasting, and anomaly detection.
"""

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from aws_services.account_manager import get_session


class CostExplorerService:
    def __init__(self):
        pass

    @property
    def session(self):
        return get_session()

    @property
    def ce(self):
        return self.session.client("ce")

    # ------------------------------------------------------------------ #
    #  Cost Summary (last 30 days vs previous 30 days)
    # ------------------------------------------------------------------ #
    def get_cost_summary(self):
        today = datetime.utcnow().date()
        start_current = (today - timedelta(days=30)).isoformat()
        end_current = today.isoformat()
        start_prev = (today - timedelta(days=60)).isoformat()
        end_prev = (today - timedelta(days=30)).isoformat()

        current = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start_current, "End": end_current},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )
        previous = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start_prev, "End": end_prev},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )

        current_total = sum(
            float(r["Total"]["UnblendedCost"]["Amount"])
            for r in current["ResultsByTime"]
        )
        previous_total = sum(
            float(r["Total"]["UnblendedCost"]["Amount"])
            for r in previous["ResultsByTime"]
        )

        pct_change = (
            ((current_total - previous_total) / previous_total * 100)
            if previous_total
            else 0
        )

        # Top service by cost
        svc = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start_current, "End": end_current},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        service_totals = {}
        for period in svc["ResultsByTime"]:
            for group in period["Groups"]:
                name = group["Keys"][0]
                amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                service_totals[name] = service_totals.get(name, 0) + amt

        top_service = max(service_totals, key=service_totals.get) if service_totals else "N/A"
        top_service_cost = service_totals.get(top_service, 0)

        return {
            "current_total": round(current_total, 2),
            "previous_total": round(previous_total, 2),
            "daily_average": round(current_total / 30, 2),
            "pct_change": round(pct_change, 2),
            "top_service": top_service,
            "top_service_cost": round(top_service_cost, 2),
        }

    # ------------------------------------------------------------------ #
    #  Daily Costs (for chart)
    # ------------------------------------------------------------------ #
    def get_daily_costs(self, days=30):
        today = datetime.utcnow().date()
        start = (today - timedelta(days=days)).isoformat()
        end = today.isoformat()

        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
        )

        return [
            {
                "date": r["TimePeriod"]["Start"],
                "cost": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2),
            }
            for r in resp["ResultsByTime"]
        ]

    # ------------------------------------------------------------------ #
    #  Daily Costs by Service (stacked area / heatmap data)
    # ------------------------------------------------------------------ #
    def get_daily_costs_by_service(self, days=30, top_n=8):
        """Return daily cost broken down by top N services."""
        today = datetime.utcnow().date()
        start = (today - timedelta(days=days)).isoformat()
        end = today.isoformat()

        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        # Aggregate totals to find top services
        service_totals = {}
        for period in resp["ResultsByTime"]:
            for group in period["Groups"]:
                name = group["Keys"][0]
                amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                service_totals[name] = service_totals.get(name, 0) + amt

        top_services = sorted(service_totals, key=service_totals.get, reverse=True)[:top_n]

        # Build per-day, per-service data
        dates = []
        service_data = {svc: [] for svc in top_services}
        other_data = []

        for period in resp["ResultsByTime"]:
            day = period["TimePeriod"]["Start"]
            dates.append(day)
            day_costs = {}
            for group in period["Groups"]:
                name = group["Keys"][0]
                amt = round(float(group["Metrics"]["UnblendedCost"]["Amount"]), 2)
                day_costs[name] = amt

            other = 0
            for svc in top_services:
                service_data[svc].append(day_costs.get(svc, 0))
            for svc_name, amt in day_costs.items():
                if svc_name not in top_services:
                    other += amt
            other_data.append(round(other, 2))

        return {
            "dates": dates,
            "services": [
                {"service": svc, "costs": service_data[svc]}
                for svc in top_services
            ],
            "other": other_data,
        }

    # ------------------------------------------------------------------ #
    #  Cost by Service (top 10)
    # ------------------------------------------------------------------ #
    def get_cost_by_service(self):
        today = datetime.utcnow().date()
        start = (today - timedelta(days=30)).isoformat()
        end = today.isoformat()

        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        service_totals = {}
        for period in resp["ResultsByTime"]:
            for group in period["Groups"]:
                name = group["Keys"][0]
                amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                service_totals[name] = service_totals.get(name, 0) + amt

        sorted_services = sorted(service_totals.items(), key=lambda x: x[1], reverse=True)[:10]
        return [
            {"service": name, "cost": round(cost, 2)}
            for name, cost in sorted_services
        ]

    # ------------------------------------------------------------------ #
    #  Monthly Cost Breakdown (last N months, with service split)
    # ------------------------------------------------------------------ #
    def get_monthly_cost_breakdown(self, months=6):
        """Return month-wise total cost + per-service breakdown."""
        today = datetime.utcnow().date()
        start = (today - relativedelta(months=months)).replace(day=1).isoformat()
        end = today.replace(day=1).isoformat()  # up to start of current month

        # Total by month
        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )
        monthly_totals = [
            {
                "month": r["TimePeriod"]["Start"][:7],
                "cost": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2),
            }
            for r in resp["ResultsByTime"]
        ]

        # By service per month
        svc_resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        monthly_services = []
        for period in svc_resp["ResultsByTime"]:
            month_label = period["TimePeriod"]["Start"][:7]
            for group in period["Groups"]:
                svc_name = group["Keys"][0]
                amt = round(float(group["Metrics"]["UnblendedCost"]["Amount"]), 2)
                if amt > 0.01:  # skip near-zero services
                    monthly_services.append({
                        "month": month_label,
                        "service": svc_name,
                        "cost": amt,
                    })

        return {
            "totals": monthly_totals,
            "services": monthly_services,
        }

    # ------------------------------------------------------------------ #
    #  Cost by Region (top regions, last 30 days)
    # ------------------------------------------------------------------ #
    def get_cost_by_region(self):
        today = datetime.utcnow().date()
        start = (today - timedelta(days=30)).isoformat()
        end = today.isoformat()

        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "REGION"}],
        )

        region_totals = {}
        for period in resp["ResultsByTime"]:
            for group in period["Groups"]:
                region = group["Keys"][0] or "global"
                amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                region_totals[region] = region_totals.get(region, 0) + amt

        sorted_regions = sorted(region_totals.items(), key=lambda x: x[1], reverse=True)
        return [
            {"region": name, "cost": round(cost, 2)}
            for name, cost in sorted_regions if cost > 0.01
        ]

    # ------------------------------------------------------------------ #
    #  Cost by Linked Account (for Organizations)
    # ------------------------------------------------------------------ #
    def get_cost_by_account(self):
        today = datetime.utcnow().date()
        start = (today - timedelta(days=30)).isoformat()
        end = today.isoformat()

        try:
            resp = self.ce.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}],
            )

            account_totals = {}
            for period in resp["ResultsByTime"]:
                for group in period["Groups"]:
                    acct_id = group["Keys"][0]
                    amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    account_totals[acct_id] = account_totals.get(acct_id, 0) + amt

            sorted_accounts = sorted(account_totals.items(), key=lambda x: x[1], reverse=True)
            return [
                {"account_id": acct_id, "cost": round(cost, 2)}
                for acct_id, cost in sorted_accounts if cost > 0.01
            ]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    #  Cost by Usage Type (for detailed analysis)
    # ------------------------------------------------------------------ #
    def get_cost_by_usage_type(self, top_n=15):
        today = datetime.utcnow().date()
        start = (today - timedelta(days=30)).isoformat()
        end = today.isoformat()

        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
        )

        usage_totals = {}
        for period in resp["ResultsByTime"]:
            for group in period["Groups"]:
                usage = group["Keys"][0]
                amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                usage_totals[usage] = usage_totals.get(usage, 0) + amt

        sorted_usage = sorted(usage_totals.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return [
            {"usage_type": name, "cost": round(cost, 2)}
            for name, cost in sorted_usage if cost > 0.01
        ]

    # ------------------------------------------------------------------ #
    #  Cost Anomalies
    # ------------------------------------------------------------------ #
    def get_cost_anomalies(self):
        today = datetime.utcnow().date()
        start = (today - timedelta(days=90)).isoformat()
        end = today.isoformat()

        try:
            resp = self.ce.get_anomalies(
                DateInterval={"StartDate": start, "EndDate": end},
                MaxResults=10,
            )
            anomalies = []
            for a in resp.get("Anomalies", []):
                anomalies.append({
                    "id": a.get("AnomalyId", ""),
                    "start_date": a.get("AnomalyStartDate", ""),
                    "end_date": a.get("AnomalyEndDate", ""),
                    "expected_spend": round(
                        float(a.get("Impact", {}).get("MaxImpact", 0)), 2
                    ),
                    "actual_spend": round(
                        float(a.get("Impact", {}).get("TotalActualSpend", 0)), 2
                    ),
                    "total_impact": round(
                        float(a.get("Impact", {}).get("TotalImpact", 0)), 2
                    ),
                    "root_causes": a.get("RootCauses", []),
                })
            return anomalies
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    #  Cost Forecast
    # ------------------------------------------------------------------ #
    def get_cost_forecast(self, months=3):
        today = datetime.utcnow().date()
        start = (today + timedelta(days=1)).isoformat()
        end = (today + relativedelta(months=months)).isoformat()

        try:
            resp = self.ce.get_cost_forecast(
                TimePeriod={"Start": start, "End": end},
                Metric="UNBLENDED_COST",
                Granularity="MONTHLY",
            )
            total_forecast = round(
                float(resp.get("Total", {}).get("Amount", 0)), 2
            )
            forecast_periods = [
                {
                    "start": fp["TimePeriod"]["Start"],
                    "end": fp["TimePeriod"]["End"],
                    "mean": round(float(fp["MeanValue"]), 2),
                    "lower": round(float(fp.get("PredictionIntervalLowerBound", fp["MeanValue"])), 2),
                    "upper": round(float(fp.get("PredictionIntervalUpperBound", fp["MeanValue"])), 2),
                }
                for fp in resp.get("ForecastResultsByTime", [])
            ]
            return {
                "total_forecast": total_forecast,
                "periods": forecast_periods,
            }
        except Exception as e:
            return {"total_forecast": 0, "periods": [], "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Monthly Cost Trend (historical)
    # ------------------------------------------------------------------ #
    def get_monthly_cost_trend(self, months=12):
        today = datetime.utcnow().date()
        start = (today - relativedelta(months=months)).replace(day=1).isoformat()
        end = today.isoformat()

        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )

        return [
            {
                "month": r["TimePeriod"]["Start"][:7],
                "cost": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2),
            }
            for r in resp["ResultsByTime"]
        ]
