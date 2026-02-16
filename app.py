from datetime import datetime, date, timedelta
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from dateutil.relativedelta import relativedelta
from config import Config
from aws_services.cost_explorer import CostExplorerService
from aws_services.recommendations import RecommendationService
from aws_services.inventory import InventoryService
from aws_services.savings_plans import SavingsPlansService
from aws_services.news import AWSNewsService
from aws_services.compute_optimizer import ComputeOptimizerService
from aws_services.cost_agent import CostOptimizationAgent
from aws_services.cost_savings_ai import CostSavingsAI
from aws_services import account_manager

app = Flask(__name__)
app.config.from_object(Config)

# Initialize services (they now use account_manager.get_session() internally)
cost_service = CostExplorerService()
recommendation_service = RecommendationService()
inventory_service = InventoryService()
savings_service = SavingsPlansService()
news_service = AWSNewsService()
compute_optimizer_service = ComputeOptimizerService()
cost_agent = CostOptimizationAgent()
cost_savings_ai = CostSavingsAI()


@app.context_processor
def inject_globals():
    """Inject global template variables available in every template."""
    active = account_manager.get_active_account()
    accounts = account_manager.list_accounts()
    return {
        "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "active_account": active,
        "all_accounts": accounts,
    }


# ================================================================== #
#  ACCOUNT MANAGEMENT  (Vantage.sh-style integration)
# ================================================================== #

@app.route('/accounts')
def accounts():
    """Account management hub."""
    accts = account_manager.list_accounts()
    return render_template('accounts.html', accounts=accts)


@app.route('/accounts/add', methods=['GET', 'POST'])
def accounts_add():
    """Add a new AWS account integration."""
    if request.method == 'POST':
        auth_type = request.form.get('auth_type', 'iam_role')
        acct, msg = account_manager.add_account(
            name=request.form.get('name', '').strip(),
            aws_account_id=request.form.get('aws_account_id', '').strip(),
            auth_type=auth_type,
            role_arn=request.form.get('role_arn', '').strip(),
            external_id=request.form.get('external_id', '').strip(),
            access_key_id=request.form.get('access_key_id', '').strip(),
            secret_access_key=request.form.get('secret_access_key', '').strip(),
            region=request.form.get('region', '').strip() or None,
        )
        if acct:
            flash(f"Account '{acct['name']}' added – {msg}", "success")
        else:
            flash(f"Failed to add account: {msg}", "danger")
        return redirect(url_for('accounts'))

    # GET – show form with CloudFormation info
    cf_template = account_manager.get_cloudformation_template()
    external_id = account_manager.EXTERNAL_ID_DEFAULT
    return render_template('accounts_add.html',
                           cf_template=cf_template,
                           external_id=external_id)


@app.route('/accounts/<account_id>/activate', methods=['POST'])
def accounts_activate(account_id):
    """Switch the active account."""
    if account_manager.set_active_account(account_id):
        acct = account_manager.get_account(account_id)
        flash(f"Switched to account '{acct['name']}'", "success")
    else:
        flash("Account not found", "danger")
    return redirect(request.referrer or url_for('accounts'))


@app.route('/accounts/<account_id>/refresh', methods=['POST'])
def accounts_refresh(account_id):
    """Re-test connection for an account."""
    acct = account_manager.refresh_account_status(account_id)
    if acct:
        flash(f"Connection test: {acct['status']} – {acct['status_message']}", "info")
    else:
        flash("Account not found", "danger")
    return redirect(url_for('accounts'))


@app.route('/accounts/<account_id>/delete', methods=['POST'])
def accounts_delete(account_id):
    """Remove an account integration."""
    if account_manager.delete_account(account_id):
        flash("Account removed", "success")
    else:
        flash("Account not found", "danger")
    return redirect(url_for('accounts'))


@app.route('/accounts/<account_id>/edit', methods=['GET', 'POST'])
def accounts_edit(account_id):
    """Edit an existing account."""
    acct = account_manager.get_account(account_id)
    if not acct:
        flash("Account not found", "danger")
        return redirect(url_for('accounts'))

    if request.method == 'POST':
        updated = account_manager.update_account(
            account_id,
            name=request.form.get('name', '').strip(),
            auth_type=request.form.get('auth_type', acct['auth_type']),
            role_arn=request.form.get('role_arn', '').strip(),
            external_id=request.form.get('external_id', '').strip(),
            access_key_id=request.form.get('access_key_id', '').strip(),
            secret_access_key=request.form.get('secret_access_key', '').strip(),
            region=request.form.get('region', '').strip() or Config.AWS_REGION,
        )
        if updated:
            # Re-test after edit
            account_manager.refresh_account_status(account_id)
            flash("Account updated", "success")
        return redirect(url_for('accounts'))

    return render_template('accounts_edit.html', account=acct)


@app.route('/accounts/refresh-all', methods=['POST'])
def accounts_refresh_all():
    """Re-test all account connections."""
    account_manager.refresh_all_statuses()
    flash("All connections refreshed", "info")
    return redirect(url_for('accounts'))


@app.route('/accounts/discover-org', methods=['POST'])
def accounts_discover_org():
    """Discover member accounts from AWS Organizations."""
    org_accounts, err = account_manager.discover_org_accounts()
    if err:
        flash(f"Organization discovery error: {err}", "danger")
    return render_template('accounts_org.html',
                           org_accounts=org_accounts, error=err)


@app.route('/api/accounts')
def api_accounts():
    """API: list accounts (for AJAX switcher)."""
    accounts = account_manager.list_accounts()
    # Strip secrets before sending to client
    safe = []
    for a in accounts:
        safe.append({k: v for k, v in a.items()
                     if k not in ('secret_access_key', 'access_key_id')})
    return jsonify(safe)


@app.route('/api/cf-template')
def api_cf_template():
    """API: download CloudFormation template."""
    return app.response_class(
        response=account_manager.get_cloudformation_template(),
        status=200,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=aws-cost-optimizer-role.json'},
    )


# ================================================================== #
#  DASHBOARD
# ================================================================== #

@app.route('/')
def dashboard():
    try:
        # Parse period from query string
        period = request.args.get('period', '30d')
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        today = date.today()

        if start_date and end_date:
            period = 'custom'
        elif period == '7d':
            start_date = (today - timedelta(days=7)).isoformat()
            end_date = today.isoformat()
        elif period == '14d':
            start_date = (today - timedelta(days=14)).isoformat()
            end_date = today.isoformat()
        elif period == '30d':
            start_date = (today - timedelta(days=30)).isoformat()
            end_date = today.isoformat()
        elif period == 'last_month':
            first_of_this = today.replace(day=1)
            last_month_end = first_of_this - timedelta(days=1)
            start_date = last_month_end.replace(day=1).isoformat()
            end_date = first_of_this.isoformat()
        elif period == '3m':
            start_date = (today - relativedelta(months=3)).isoformat()
            end_date = today.isoformat()
        elif period == '6m':
            start_date = (today - relativedelta(months=6)).isoformat()
            end_date = today.isoformat()
        elif period == 'ytd':
            start_date = today.replace(month=1, day=1).isoformat()
            end_date = today.isoformat()
        elif period == '12m':
            start_date = (today - relativedelta(months=12)).isoformat()
            end_date = today.isoformat()
        else:
            start_date = (today - timedelta(days=30)).isoformat()
            end_date = today.isoformat()

        summary = cost_service.get_cost_summary(start=start_date, end=end_date)
        daily_costs = cost_service.get_daily_costs(start=start_date, end=end_date)
        service_costs = cost_service.get_cost_by_service(start=start_date, end=end_date)
        anomalies = cost_service.get_cost_anomalies()
        monthly_costs = cost_service.get_monthly_cost_breakdown(months=6)
        region_costs = cost_service.get_cost_by_region(start=start_date, end=end_date)
        account_costs = cost_service.get_cost_by_account(start=start_date, end=end_date)
        usage_type_costs = cost_service.get_cost_by_usage_type(start=start_date, end=end_date)
        co_summary = compute_optimizer_service.get_optimization_summary()
        return render_template('dashboard.html',
                               summary=summary,
                               daily_costs=daily_costs,
                               service_costs=service_costs,
                               anomalies=anomalies,
                               monthly_costs=monthly_costs,
                               region_costs=region_costs,
                               account_costs=account_costs,
                               usage_type_costs=usage_type_costs,
                               co_summary=co_summary,
                               current_period=period,
                               period_start=start_date,
                               period_end=end_date)
    except Exception as e:
        return render_template('dashboard.html',
                               error=str(e),
                               summary={},
                               daily_costs=[],
                               service_costs=[],
                               anomalies=[],
                               monthly_costs={'totals': [], 'services': []},
                               region_costs=[],
                               account_costs=[],
                               usage_type_costs=[],
                               co_summary={},
                               current_period=request.args.get('period', '30d'),
                               period_start='',
                               period_end='')


# ================================================================== #
#  RECOMMENDATIONS
# ================================================================== #

@app.route('/recommendations')
def recommendations():
    try:
        rightsizing = recommendation_service.get_rightsizing_recommendations()
        trusted_advisor = recommendation_service.get_trusted_advisor_checks()
        idle_resources = recommendation_service.get_idle_resources()
        co_ec2 = compute_optimizer_service.get_ec2_recommendations()
        co_ebs = compute_optimizer_service.get_ebs_recommendations()
        co_lambda = compute_optimizer_service.get_lambda_recommendations()
        return render_template('recommendations.html',
                               rightsizing=rightsizing,
                               trusted_advisor=trusted_advisor,
                               idle_resources=idle_resources,
                               co_ec2=co_ec2,
                               co_ebs=co_ebs,
                               co_lambda=co_lambda)
    except Exception as e:
        return render_template('recommendations.html',
                               error=str(e),
                               rightsizing=[],
                               trusted_advisor=[],
                               idle_resources=[],
                               co_ec2={},
                               co_ebs={},
                               co_lambda={})


# ================================================================== #
#  RESOURCE INVENTORY
# ================================================================== #

@app.route('/inventory')
def inventory():
    try:
        resources = inventory_service.get_all_resources()
        return render_template('inventory.html', resources=resources)
    except Exception as e:
        return render_template('inventory.html',
                               error=str(e),
                               resources={})


# ================================================================== #
#  SAVINGS PLANS / RESERVATIONS
# ================================================================== #

@app.route('/savings-plans')
def savings_plans():
    try:
        plans = savings_service.get_savings_plans()
        ri_data = savings_service.get_reserved_instances()
        coverage = savings_service.get_savings_plan_coverage()
        utilization = savings_service.get_savings_plan_utilization()
        sp_recommendations = savings_service.get_savings_plan_recommendations()
        return render_template('savings_plans.html',
                               plans=plans,
                               ri_data=ri_data,
                               coverage=coverage,
                               utilization=utilization,
                               sp_recommendations=sp_recommendations)
    except Exception as e:
        return render_template('savings_plans.html',
                               error=str(e),
                               plans=[],
                               ri_data=[],
                               coverage={},
                               utilization={},
                               sp_recommendations=[])


# ================================================================== #
#  FORECAST
# ================================================================== #

@app.route('/forecast')
def forecast():
    try:
        forecast_data = cost_service.get_cost_forecast(months=12)
        monthly_trend = cost_service.get_monthly_cost_trend(months=12)
        return render_template('forecast.html',
                               forecast_data=forecast_data,
                               monthly_trend=monthly_trend)
    except Exception as e:
        return render_template('forecast.html',
                               error=str(e),
                               forecast_data={},
                               monthly_trend=[])


# ================================================================== #
#  COST SAVINGS OPPORTUNITIES (AI/ML)
# ================================================================== #

@app.route('/savings-opportunities')
def savings_opportunities():
    """AI/ML-powered cost savings analysis — dedicated page."""
    return render_template('savings_opportunities.html')


# ================================================================== #
#  AWS NEWS
# ================================================================== #

@app.route('/news')
def news():
    try:
        articles = news_service.get_latest_news(limit=20)
        return render_template('news.html', articles=articles)
    except Exception as e:
        return render_template('news.html',
                               error=str(e),
                               articles=[])


# ================================================================== #
#  API ENDPOINTS (for AJAX charts)
# ================================================================== #

@app.route('/api/daily-costs')
def api_daily_costs():
    start = request.args.get('start')
    end = request.args.get('end')
    days = int(request.args.get('days', 30))
    data = cost_service.get_daily_costs(days=days, start=start, end=end)
    return jsonify(data)

@app.route('/api/service-costs')
def api_service_costs():
    start = request.args.get('start')
    end = request.args.get('end')
    data = cost_service.get_cost_by_service(start=start, end=end)
    return jsonify(data)

@app.route('/api/monthly-costs')
def api_monthly_costs():
    months = int(request.args.get('months', 6))
    data = cost_service.get_monthly_cost_breakdown(months=months)
    return jsonify(data)

@app.route('/api/daily-service-costs')
def api_daily_service_costs():
    start = request.args.get('start')
    end = request.args.get('end')
    days = int(request.args.get('days', 30))
    data = cost_service.get_daily_costs_by_service(days=days, top_n=8, start=start, end=end)
    return jsonify(data)

@app.route('/api/forecast-data')
def api_forecast_data():
    data = cost_service.get_cost_forecast(months=12)
    return jsonify(data)


@app.route('/api/region-costs')
def api_region_costs():
    start = request.args.get('start')
    end = request.args.get('end')
    data = cost_service.get_cost_by_region(start=start, end=end)
    return jsonify(data)


@app.route('/api/account-costs')
def api_account_costs():
    start = request.args.get('start')
    end = request.args.get('end')
    data = cost_service.get_cost_by_account(start=start, end=end)
    return jsonify(data)


@app.route('/api/usage-type-costs')
def api_usage_type_costs():
    start = request.args.get('start')
    end = request.args.get('end')
    data = cost_service.get_cost_by_usage_type(top_n=15, start=start, end=end)
    return jsonify(data)


@app.route('/api/compute-optimizer')
def api_compute_optimizer():
    data = compute_optimizer_service.get_optimization_summary()
    return jsonify(data)


@app.route('/api/cost-savings-ai')
def api_cost_savings_ai():
    """API: AI/ML-powered cost savings opportunities."""
    try:
        data = cost_savings_ai.generate_opportunities()
        return jsonify({"opportunities": data, "count": len(data),
                        "total_savings": round(sum(o["estimated_savings"] for o in data), 2)})
    except Exception as e:
        return jsonify({"error": str(e), "opportunities": [], "count": 0, "total_savings": 0}), 500


# ================================================================== #
#  COST OPTIMIZATION AGENT
# ================================================================== #

@app.route('/agent')
def agent_page():
    """Cost Optimization Agent — intelligent FinOps advisor."""
    return render_template('agent.html')


@app.route('/api/agent/run', methods=['POST'])
def api_agent_run():
    """Run the full cost optimization agent analysis."""
    try:
        report = cost_agent.run_full_analysis()
        return jsonify(report)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)