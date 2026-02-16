from flask import Flask, render_template, jsonify
from config import Config
from aws_services.cost_explorer import CostExplorerService
from aws_services.recommendations import RecommendationService
from aws_services.inventory import InventoryService
from aws_services.savings_plans import SavingsPlansService
from aws_services.news import AWSNewsService

app = Flask(__name__)
app.config.from_object(Config)

# Initialize services
cost_service = CostExplorerService()
recommendation_service = RecommendationService()
inventory_service = InventoryService()
savings_service = SavingsPlansService()
news_service = AWSNewsService()


# --- DASHBOARD ---
@app.route('/')
def dashboard():
    try:
        summary = cost_service.get_cost_summary()
        daily_costs = cost_service.get_daily_costs(days=30)
        service_costs = cost_service.get_cost_by_service()
        anomalies = cost_service.get_cost_anomalies()
        return render_template('dashboard.html',
                               summary=summary,
                               daily_costs=daily_costs,
                               service_costs=service_costs,
                               anomalies=anomalies)
    except Exception as e:
        return render_template('dashboard.html', error=str(e))


# --- RECOMMENDATIONS ---
@app.route('/recommendations')
def recommendations():
    try:
        rightsizing = recommendation_service.get_rightsizing_recommendations()
        trusted_advisor = recommendation_service.get_trusted_advisor_checks()
        idle_resources = recommendation_service.get_idle_resources()
        return render_template('recommendations.html',
                               rightsizing=rightsizing,
                               trusted_advisor=trusted_advisor,
                               idle_resources=idle_resources)
    except Exception as e:
        return render_template('recommendations.html', error=str(e))


# --- RESOURCE INVENTORY ---
@app.route('/inventory')
def inventory():
    try:
        resources = inventory_service.get_all_resources()
        return render_template('inventory.html', resources=resources)
    except Exception as e:
        return render_template('inventory.html', error=str(e))


# --- SAVINGS PLANS / RESERVATIONS ---
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
        return render_template('savings_plans.html', error=str(e))


# --- FORECAST ---
@app.route('/forecast')
def forecast():
    try:
        forecast_data = cost_service.get_cost_forecast(months=12)
        monthly_trend = cost_service.get_monthly_cost_trend(months=12)
        return render_template('forecast.html',
                               forecast_data=forecast_data,
                               monthly_trend=monthly_trend)
    except Exception as e:
        return render_template('forecast.html', error=str(e))


# --- AWS NEWS ---
@app.route('/news')
def news():
    try:
        articles = news_service.get_latest_news(limit=20)
        return render_template('news.html', articles=articles)
    except Exception as e:
        return render_template('news.html', error=str(e))


# --- API ENDPOINTS (for AJAX charts) ---
@app.route('/api/daily-costs')
def api_daily_costs():
    data = cost_service.get_daily_costs(days=30)
    return jsonify(data)

@app.route('/api/service-costs')
def api_service_costs():
    data = cost_service.get_cost_by_service()
    return jsonify(data)

@app.route('/api/forecast-data')
def api_forecast_data():
    data = cost_service.get_cost_forecast(months=12)
    return jsonify(data)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)