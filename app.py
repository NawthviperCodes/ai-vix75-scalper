# === app.py ===
from flask import Flask, render_template, request, jsonify, redirect, url_for
from performance_tracker import get_live_stats
from threading import Thread
from flask_cors import CORS
from main import run_bot, stop_bot

app = Flask(__name__)
CORS(app)

# === Bot State ===
bot_thread = None
bot_status = {
    "running": False,
    "strategy": None,
    "lot": None
}

# === Home Landing Page ===
@app.route("/")
def home():
    return render_template("home.html")

# === Dashboard ===
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# === Start/Stop Bot Control ===
@app.route("/dashboard", methods=["POST"])
def control_bot():
    global bot_thread, bot_status
    data = request.form or request.json
    action = data.get("action")
    strategy = data.get("strategy")
    lot_size = float(data.get("lot_size", 0.001))

    if action == "start" and not bot_status["running"]:
        bot_thread = Thread(target=run_bot, args=(strategy, lot_size))
        bot_thread.start()
        bot_status.update({
            "running": True,
            "strategy": strategy,
            "lot": lot_size
        })
        return jsonify({"message": "Bot started"}), 200

    elif action == "stop" and bot_status["running"]:
        stop_bot()
        bot_status.update({
            "running": False,
            "strategy": None,
            "lot": None
        })
        return jsonify({"message": "Bot stopped"}), 200

    return jsonify({"message": "No action taken"}), 400

# === Bot Status ===
@app.route("/status", methods=["GET"])
def get_status():
    return jsonify(bot_status)

# === Live Stats Endpoint ===
@app.route("/stats", methods=["GET"])
def get_stats():
    return jsonify(get_live_stats())

# === Static Routes for Future Expansion ===
@app.route("/about")
def about():
    return redirect(url_for("home") + "#about")

@app.route("/login")
def login():
    return "<h2 style='color:white; text-align:center; margin-top:100px;'>🔐 Login Coming Soon</h2>"

@app.route("/register")
def register():
    return "<h2 style='color:white; text-align:center; margin-top:100px;'>📝 Register Coming Soon</h2>"

# === Run Server ===
if __name__ == "__main__":
    app.run(debug=True)
