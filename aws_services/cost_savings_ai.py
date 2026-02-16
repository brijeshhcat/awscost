"""
AI/ML-Powered Cost Savings Opportunities Engine
─────────────────────────────────────────────────
Analyses real-time AWS cost data using statistical methods and heuristic ML
to generate intelligent, actionable savings recommendations.

Techniques used:
 • Trend analysis        – linear-regression on daily costs to detect runaway spend
 • Spike detection       – z-score anomaly flagging for sudden service-cost surges
 • Service concentration – Herfindahl-Hirschman Index to find over-reliance risk
 • Region optimization   – detects underused expensive regions
 • Usage-type profiling  – identifies data-transfer / storage waste patterns
 • Idle resource signals – flags services with low but persistent daily costs
 • Scheduling gaps       – identifies on/off patterns that suggest stop-start savings
 • Savings Plans / RI    – analyses coverage gaps from Cost Explorer
"""

import math
import logging
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from aws_services.account_manager import get_session

logger = logging.getLogger(__name__)


# ──────────────────── Helper math utilities ──────────────────── #

def _linear_regression(ys):
    """Simple OLS on [0..n-1] → ys.  Returns (slope, r_squared)."""
    n = len(ys)
    if n < 3:
        return 0, 0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_yy = sum((y - mean_y) ** 2 for y in ys)
    if ss_xx == 0:
        return 0, 0
    slope = ss_xy / ss_xx
    r_sq = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy else 0
    return slope, r_sq


def _z_scores(values):
    """Return list of z-scores for a numeric series."""
    n = len(values)
    if n < 3:
        return [0] * n
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / n) or 1
    return [(v - mean) / std for v in values]


def _hhi(shares):
    """Herfindahl-Hirschman Index (0–10000) for market/share concentration."""
    total = sum(shares) or 1
    return sum(((s / total) * 100) ** 2 for s in shares)


# ──────────────────── Main Engine ──────────────────── #

class CostSavingsAI:
    """Generates AI/ML-powered cost savings suggestions from live AWS data."""

    PRIORITY_MAP = {"critical": 4, "high": 3, "medium": 2, "low": 1}

    def __init__(self):
        pass

    @property
    def session(self):
        return get_session()

    @property
    def ce(self):
        return self.session.client("ce")

    # ── public entry point ─────────────────────────── #
    def generate_opportunities(self):
        """
        Analyse current account cost data and return a list of savings
        opportunity dicts sorted by estimated savings (desc).
        Each item:
            { id, title, description, category, priority,
              estimated_savings, confidence, icon, actions[] }
        """
        opportunities = []
        try:
            # 1 — gather raw data (parallel-safe; all read-only)
            daily       = self._fetch_daily_costs(60)
            services    = self._fetch_service_costs(30)
            regions     = self._fetch_region_costs(30)
            usage_types = self._fetch_usage_type_costs(30)
            monthly     = self._fetch_monthly_totals(6)
            daily_svc   = self._fetch_daily_service_costs(30, 8)

            # 2 — run analysis modules
            opportunities += self._analyse_cost_trend(daily)
            opportunities += self._analyse_service_concentration(services)
            opportunities += self._analyse_service_spikes(daily_svc)
            opportunities += self._analyse_region_waste(regions)
            opportunities += self._analyse_data_transfer(usage_types)
            opportunities += self._analyse_idle_services(services, daily_svc)
            opportunities += self._analyse_monthly_growth(monthly)
            opportunities += self._analyse_scheduling_opportunities(daily)
            opportunities += self._analyse_storage_optimization(usage_types)
            opportunities += self._analyse_savings_plan_coverage()

        except Exception as exc:
            logger.exception("CostSavingsAI.generate_opportunities failed")
            opportunities.append({
                "id": "err-001",
                "title": "Analysis Incomplete",
                "description": f"Some analyses could not complete: {exc}",
                "category": "system",
                "priority": "low",
                "estimated_savings": 0,
                "confidence": 0,
                "icon": "bi-exclamation-triangle",
                "actions": [],
            })

        # de-duplicate by id, sort by savings desc
        seen = set()
        unique = []
        for o in opportunities:
            if o["id"] not in seen:
                seen.add(o["id"])
                unique.append(o)
        unique.sort(key=lambda x: x["estimated_savings"], reverse=True)
        return unique

    # ──────────────────── Data fetchers ──────────────────── #

    def _fetch_daily_costs(self, days=60):
        today = datetime.utcnow().date()
        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": (today - timedelta(days=days)).isoformat(), "End": today.isoformat()},
            Granularity="DAILY", Metrics=["UnblendedCost"],
        )
        return [
            {"date": r["TimePeriod"]["Start"],
             "cost": round(float(r["Total"]["UnblendedCost"]["Amount"]), 4)}
            for r in resp["ResultsByTime"]
        ]

    def _fetch_service_costs(self, days=30):
        today = datetime.utcnow().date()
        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": (today - timedelta(days=days)).isoformat(), "End": today.isoformat()},
            Granularity="MONTHLY", Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        totals = {}
        for p in resp["ResultsByTime"]:
            for g in p["Groups"]:
                name = g["Keys"][0]
                totals[name] = totals.get(name, 0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
        return sorted(
            [{"service": k, "cost": round(v, 2)} for k, v in totals.items()],
            key=lambda x: x["cost"], reverse=True,
        )

    def _fetch_region_costs(self, days=30):
        today = datetime.utcnow().date()
        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": (today - timedelta(days=days)).isoformat(), "End": today.isoformat()},
            Granularity="MONTHLY", Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "REGION"}],
        )
        totals = {}
        for p in resp["ResultsByTime"]:
            for g in p["Groups"]:
                r = g["Keys"][0] or "global"
                totals[r] = totals.get(r, 0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
        return sorted(
            [{"region": k, "cost": round(v, 2)} for k, v in totals.items()],
            key=lambda x: x["cost"], reverse=True,
        )

    def _fetch_usage_type_costs(self, days=30):
        today = datetime.utcnow().date()
        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": (today - timedelta(days=days)).isoformat(), "End": today.isoformat()},
            Granularity="MONTHLY", Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
        )
        totals = {}
        for p in resp["ResultsByTime"]:
            for g in p["Groups"]:
                totals[g["Keys"][0]] = totals.get(g["Keys"][0], 0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
        return sorted(
            [{"usage_type": k, "cost": round(v, 2)} for k, v in totals.items()],
            key=lambda x: x["cost"], reverse=True,
        )[:25]

    def _fetch_monthly_totals(self, months=6):
        today = datetime.utcnow().date()
        start = (today - relativedelta(months=months)).replace(day=1).isoformat()
        end = today.replace(day=1).isoformat()
        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY", Metrics=["UnblendedCost"],
        )
        return [
            {"month": r["TimePeriod"]["Start"][:7],
             "cost": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2)}
            for r in resp["ResultsByTime"]
        ]

    def _fetch_daily_service_costs(self, days=30, top_n=8):
        today = datetime.utcnow().date()
        resp = self.ce.get_cost_and_usage(
            TimePeriod={"Start": (today - timedelta(days=days)).isoformat(), "End": today.isoformat()},
            Granularity="DAILY", Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        svc_totals = {}
        for p in resp["ResultsByTime"]:
            for g in p["Groups"]:
                n = g["Keys"][0]
                svc_totals[n] = svc_totals.get(n, 0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
        top = sorted(svc_totals, key=svc_totals.get, reverse=True)[:top_n]

        svc_daily = {s: [] for s in top}
        dates = []
        for p in resp["ResultsByTime"]:
            dates.append(p["TimePeriod"]["Start"])
            day_map = {}
            for g in p["Groups"]:
                day_map[g["Keys"][0]] = float(g["Metrics"]["UnblendedCost"]["Amount"])
            for s in top:
                svc_daily[s].append(round(day_map.get(s, 0), 4))
        return {"dates": dates, "services": top, "data": svc_daily}

    # ──────────────────── Analysis Modules ──────────────────── #

    def _analyse_cost_trend(self, daily):
        """Detect upward trend in daily spend with linear regression."""
        opps = []
        if len(daily) < 14:
            return opps
        costs = [d["cost"] for d in daily]
        slope, r_sq = _linear_regression(costs)
        avg = sum(costs) / len(costs)

        if slope > 0 and r_sq > 0.3 and avg > 0:
            projected_30d_increase = slope * 30
            pct_increase = (projected_30d_increase / avg) * 100
            if pct_increase > 5:
                opps.append({
                    "id": "trend-001",
                    "title": "Rising Cost Trend Detected",
                    "description": (
                        f"AI analysis shows daily spend is increasing by ~${slope:.2f}/day "
                        f"(R²={r_sq:.2f}). At this rate, costs will rise {pct_increase:.0f}% "
                        f"over the next 30 days — an additional ~${projected_30d_increase:.2f}."
                    ),
                    "category": "trend",
                    "priority": "critical" if pct_increase > 20 else "high",
                    "estimated_savings": round(projected_30d_increase * 0.4, 2),
                    "confidence": round(r_sq * 100, 0),
                    "icon": "bi-graph-up-arrow",
                    "actions": [
                        "Review new resources launched in the last 14 days",
                        "Set up AWS Budget alerts at current spend level",
                        "Investigate top-growing services for optimization",
                    ],
                })

        # Also check last-7-day vs prior-7-day spike
        if len(costs) >= 14:
            recent = sum(costs[-7:])
            prior = sum(costs[-14:-7])
            if prior > 0:
                wow_pct = ((recent - prior) / prior) * 100
                if wow_pct > 15:
                    opps.append({
                        "id": "trend-002",
                        "title": f"Week-over-Week Spend Spike ({wow_pct:.0f}%)",
                        "description": (
                            f"Last 7 days total ${recent:.2f} vs prior 7 days ${prior:.2f}. "
                            f"This {wow_pct:.0f}% jump needs immediate investigation."
                        ),
                        "category": "anomaly",
                        "priority": "critical" if wow_pct > 40 else "high",
                        "estimated_savings": round((recent - prior) * 0.5, 2),
                        "confidence": 85,
                        "icon": "bi-exclamation-diamond",
                        "actions": [
                            "Compare service-by-service costs for last 7 vs prior 7 days",
                            "Check for any new deployments or auto-scaling events",
                            "Review CloudTrail for unusual API activity",
                        ],
                    })
        return opps

    def _analyse_service_concentration(self, services):
        """Detect over-reliance on a single service (Herfindahl Index)."""
        opps = []
        if not services:
            return opps
        costs = [s["cost"] for s in services if s["cost"] > 0]
        total = sum(costs) or 1
        hhi = _hhi(costs)

        # HHI > 2500 = highly concentrated
        if hhi > 2500 and len(services) >= 2:
            top = services[0]
            share = (top["cost"] / total) * 100
            opps.append({
                "id": "conc-001",
                "title": f"High Spend Concentration: {top['service']}",
                "description": (
                    f"{top['service']} accounts for {share:.0f}% of total spend "
                    f"(${top['cost']:.2f}). High concentration (HHI={hhi:.0f}) "
                    f"increases risk — optimizing this one service can dramatically cut costs."
                ),
                "category": "optimization",
                "priority": "high" if share > 60 else "medium",
                "estimated_savings": round(top["cost"] * 0.15, 2),
                "confidence": 80,
                "icon": "bi-pie-chart",
                "actions": [
                    f"Deep-dive into {top['service']} usage-type breakdown",
                    "Evaluate Reserved Instances or Savings Plans for this service",
                    "Check for over-provisioned or idle resources",
                ],
            })
        return opps

    def _analyse_service_spikes(self, daily_svc):
        """Z-score per-service analysis to find sudden cost surges."""
        opps = []
        for svc in daily_svc.get("services", []):
            costs = daily_svc["data"].get(svc, [])
            if len(costs) < 7:
                continue
            zs = _z_scores(costs)
            recent_max_z = max(zs[-7:]) if zs else 0
            if recent_max_z > 2.0:
                peak_day_idx = len(costs) - 7 + zs[-7:].index(max(zs[-7:]))
                peak_cost = costs[peak_day_idx]
                avg_cost = sum(costs) / len(costs)
                excess = peak_cost - avg_cost
                if excess > 0.5:
                    svc_short = svc.replace("Amazon ", "").replace("AWS ", "")
                    opps.append({
                        "id": f"spike-{svc_short[:15].replace(' ','-').lower()}",
                        "title": f"Cost Spike in {svc_short}",
                        "description": (
                            f"Anomalous spend detected for {svc_short} — "
                            f"peak ${peak_cost:.2f}/day vs avg ${avg_cost:.2f}/day "
                            f"(z-score {recent_max_z:.1f}). Investigate for unexpected usage."
                        ),
                        "category": "anomaly",
                        "priority": "high" if recent_max_z > 3 else "medium",
                        "estimated_savings": round(excess * 7, 2),
                        "confidence": min(95, round(50 + recent_max_z * 15)),
                        "icon": "bi-lightning",
                        "actions": [
                            f"Review {svc_short} CloudWatch metrics for the spike period",
                            "Check auto-scaling events or new resource launches",
                            f"Set a per-service budget alert for {svc_short}",
                        ],
                    })
        return opps

    def _analyse_region_waste(self, regions):
        """Detect expensive secondary regions that may host idle resources."""
        opps = []
        if len(regions) < 2:
            return opps
        total = sum(r["cost"] for r in regions) or 1
        primary = regions[0]
        for r in regions[1:]:
            share = (r["cost"] / total) * 100
            if 1 < share < 15 and r["cost"] > 5:
                opps.append({
                    "id": f"region-{r['region'][:20]}",
                    "title": f"Low-Utilization Region: {r['region']}",
                    "description": (
                        f"{r['region']} has ${r['cost']:.2f} spend ({share:.1f}% of total). "
                        f"Secondary regions often contain forgotten test environments or "
                        f"unoptimized replicas. Consolidating to {primary['region']} could save costs."
                    ),
                    "category": "infrastructure",
                    "priority": "medium",
                    "estimated_savings": round(r["cost"] * 0.3, 2),
                    "confidence": 60,
                    "icon": "bi-globe-americas",
                    "actions": [
                        f"Audit all resources in {r['region']}",
                        "Identify and terminate unused dev/test resources",
                        f"Consider moving workloads to {primary['region']} if latency permits",
                    ],
                })
        return opps

    def _analyse_data_transfer(self, usage_types):
        """Identify data-transfer costs that can often be reduced."""
        opps = []
        dt_cost = 0
        dt_items = []
        for u in usage_types:
            ut = u["usage_type"].lower()
            if any(kw in ut for kw in ("datatransfer", "data-transfer", "cloudfront", "nat-gateway", "bytes")):
                dt_cost += u["cost"]
                dt_items.append(u)

        if dt_cost > 10:
            opps.append({
                "id": "dt-001",
                "title": f"Data Transfer Costs: ${dt_cost:.2f}",
                "description": (
                    f"Data transfer charges total ${dt_cost:.2f} across {len(dt_items)} usage types. "
                    f"Common savings: use VPC endpoints, CloudFront caching, S3 Transfer Acceleration, "
                    f"or consolidate cross-AZ traffic."
                ),
                "category": "networking",
                "priority": "high" if dt_cost > 100 else "medium",
                "estimated_savings": round(dt_cost * 0.25, 2),
                "confidence": 70,
                "icon": "bi-arrow-left-right",
                "actions": [
                    "Enable VPC Endpoints for S3 and DynamoDB",
                    "Review NAT Gateway usage — consider NAT instances for dev",
                    "Use CloudFront to cache static content and reduce origin fetches",
                    "Consolidate cross-AZ data transfers where possible",
                ],
            })
        return opps

    def _analyse_idle_services(self, services, daily_svc):
        """Detect services with low persistent cost (likely idle resources)."""
        opps = []
        for svc_item in services:
            cost = svc_item["cost"]
            svc = svc_item["service"]
            svc_short = svc.replace("Amazon ", "").replace("AWS ", "")
            daily = daily_svc["data"].get(svc, [])

            # Low but consistent spend => likely idle
            if 0.5 < cost < 50 and len(daily) >= 7:
                std = math.sqrt(sum((d - cost / max(len(daily), 1)) ** 2 for d in daily) / max(len(daily), 1)) if daily else 0
                avg_daily = cost / 30
                if std < avg_daily * 0.5 and avg_daily > 0.01:
                    opps.append({
                        "id": f"idle-{svc_short[:15].replace(' ', '-').lower()}",
                        "title": f"Potential Idle Resources: {svc_short}",
                        "description": (
                            f"{svc_short} has flat daily spend (~${avg_daily:.2f}/day), "
                            f"suggesting idle or underutilized resources. Total: ${cost:.2f}/month."
                        ),
                        "category": "waste",
                        "priority": "medium" if cost > 15 else "low",
                        "estimated_savings": round(cost * 0.6, 2),
                        "confidence": 55,
                        "icon": "bi-moon-stars",
                        "actions": [
                            f"Review active resources under {svc_short}",
                            "Terminate unused EC2 instances, EBS volumes, or Elastic IPs",
                            "Set up scheduled stop/start for non-production resources",
                        ],
                    })
        return opps[:5]  # cap idle suggestions

    def _analyse_monthly_growth(self, monthly):
        """Month-over-month growth trend from historical data."""
        opps = []
        if len(monthly) < 3:
            return opps
        costs = [m["cost"] for m in monthly]
        slope, r_sq = _linear_regression(costs)

        if slope > 0 and r_sq > 0.4:
            avg = sum(costs) / len(costs)
            growth_pct = (slope / avg) * 100 if avg else 0
            if growth_pct > 8:
                opps.append({
                    "id": "grow-001",
                    "title": f"Sustained Monthly Growth ({growth_pct:.0f}%/month)",
                    "description": (
                        f"ML trend analysis over {len(monthly)} months shows costs growing "
                        f"~${slope:.2f}/month ({growth_pct:.0f}% MoM). Without intervention, "
                        f"next quarter spend may increase by ~${slope * 3:.2f}."
                    ),
                    "category": "trend",
                    "priority": "high" if growth_pct > 15 else "medium",
                    "estimated_savings": round(slope * 3 * 0.35, 2),
                    "confidence": round(r_sq * 100),
                    "icon": "bi-arrow-up-right-circle",
                    "actions": [
                        "Implement cost allocation tags for all resources",
                        "Review and right-size EC2 instances monthly",
                        "Establish a FinOps review cadence (weekly/biweekly)",
                    ],
                })
        return opps

    def _analyse_scheduling_opportunities(self, daily):
        """Detect weekday vs weekend patterns suggesting scheduling savings."""
        opps = []
        if len(daily) < 14:
            return opps

        weekday_costs = []
        weekend_costs = []
        for d in daily:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            if dt.weekday() < 5:
                weekday_costs.append(d["cost"])
            else:
                weekend_costs.append(d["cost"])

        if not weekday_costs or not weekend_costs:
            return opps

        avg_weekday = sum(weekday_costs) / len(weekday_costs)
        avg_weekend = sum(weekend_costs) / len(weekend_costs)

        if avg_weekday > 0 and avg_weekend > avg_weekday * 0.6:
            # Weekend spend is still high — opportunity to schedule shutdowns
            weekend_excess = (avg_weekend - avg_weekday * 0.3) * 8  # ~8 weekend days/month
            if weekend_excess > 5:
                opps.append({
                    "id": "sched-001",
                    "title": "Weekend Scheduling Opportunity",
                    "description": (
                        f"Weekend spend avg ${avg_weekend:.2f}/day is close to weekday "
                        f"avg ${avg_weekday:.2f}/day, suggesting non-production resources "
                        f"run 24/7. Scheduling shutdowns could save ~${weekend_excess:.2f}/month."
                    ),
                    "category": "scheduling",
                    "priority": "medium",
                    "estimated_savings": round(weekend_excess, 2),
                    "confidence": 65,
                    "icon": "bi-clock-history",
                    "actions": [
                        "Tag dev/test resources with auto-stop schedules",
                        "Use AWS Instance Scheduler for EC2 and RDS",
                        "Create Lambda functions to stop/start non-prod resources",
                    ],
                })

        # Off-hours: check if nighttime could help (proxy: variance check)
        if avg_weekday > 0:
            cv = (sum((c - avg_weekday) ** 2 for c in weekday_costs) / len(weekday_costs)) ** 0.5 / avg_weekday
            if cv < 0.15 and avg_weekday > 5:
                opps.append({
                    "id": "sched-002",
                    "title": "Flat Spend Pattern — Schedule Optimization",
                    "description": (
                        f"Daily costs are remarkably consistent (CV={cv:.2f}), indicating "
                        f"24/7 operation. For non-production workloads, scheduling 12-hour "
                        f"run windows could cut costs by ~40%."
                    ),
                    "category": "scheduling",
                    "priority": "medium",
                    "estimated_savings": round(avg_weekday * 30 * 0.35, 2),
                    "confidence": 60,
                    "icon": "bi-calendar-range",
                    "actions": [
                        "Identify non-production workloads running 24/7",
                        "Implement 12-hour run schedules for dev/staging",
                        "Use AWS Instance Scheduler or custom Lambda",
                    ],
                })
        return opps

    def _analyse_storage_optimization(self, usage_types):
        """Identify storage usage types eligible for tiering."""
        opps = []
        storage_cost = 0
        storage_items = []
        for u in usage_types:
            ut = u["usage_type"].lower()
            if any(kw in ut for kw in ("storage", "ebs", "s3", "snapshot", "backup")):
                storage_cost += u["cost"]
                storage_items.append(u)

        if storage_cost > 10:
            opps.append({
                "id": "stor-001",
                "title": f"Storage Optimization: ${storage_cost:.2f}",
                "description": (
                    f"Storage-related costs total ${storage_cost:.2f}. ML analysis suggests "
                    f"reviewing S3 lifecycle policies, EBS snapshot retention, and moving "
                    f"infrequently-accessed data to S3 Glacier or Intelligent-Tiering."
                ),
                "category": "storage",
                "priority": "high" if storage_cost > 100 else "medium",
                "estimated_savings": round(storage_cost * 0.3, 2),
                "confidence": 72,
                "icon": "bi-device-hdd",
                "actions": [
                    "Enable S3 Intelligent-Tiering on frequently written buckets",
                    "Set S3 lifecycle policies to move old objects to Glacier",
                    "Delete orphaned EBS snapshots older than 90 days",
                    "Review and clean up unused AMIs",
                ],
            })
        return opps

    def _analyse_savings_plan_coverage(self):
        """Check Savings Plans coverage — low coverage means RI/SP opportunity."""
        opps = []
        try:
            today = datetime.utcnow().date()
            start = (today - timedelta(days=30)).isoformat()
            end = today.isoformat()

            resp = self.ce.get_savings_plans_coverage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
            )
            for result in resp.get("SavingsPlansCoverages", []):
                coverage = result.get("Coverage", {})
                pct = float(coverage.get("CoveragePercentage", "0") or "0")
                on_demand = float(coverage.get("OnDemandCost", "0") or "0")

                if pct < 60 and on_demand > 50:
                    potential = on_demand * 0.25  # SPs typically save ~25%
                    opps.append({
                        "id": "sp-001",
                        "title": f"Low Savings Plans Coverage ({pct:.0f}%)",
                        "description": (
                            f"Only {pct:.0f}% of eligible spend is covered by Savings Plans. "
                            f"On-demand spend is ${on_demand:.2f}. Purchasing Compute Savings Plans "
                            f"could save up to ${potential:.2f}/month (~25% on uncovered spend)."
                        ),
                        "category": "commitment",
                        "priority": "critical" if pct < 30 else "high",
                        "estimated_savings": round(potential, 2),
                        "confidence": 88,
                        "icon": "bi-piggy-bank",
                        "actions": [
                            "Review AWS Savings Plans recommendations in Cost Explorer",
                            "Start with 1-year No Upfront Compute Savings Plan",
                            "Target services with stable baseline: EC2, Fargate, Lambda",
                            "Purchase gradually — cover 60-80% of baseline first",
                        ],
                    })
        except Exception:
            pass  # Savings Plans API may not be available
        return opps
