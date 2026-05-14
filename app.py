from flask import Flask
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# ── Registrar Blueprints ──────────────────────────────────────────
from routes.auth        import auth_bp
from routes.vacantes    import vacantes_bp
from routes.postulantes import postulantes_bp
from routes.dashboard   import dashboard_bp

app.register_blueprint(auth_bp)
app.register_blueprint(vacantes_bp)
app.register_blueprint(postulantes_bp)
app.register_blueprint(dashboard_bp)

# ── Punto de entrada ──────────────────────────────────────────────
if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000))
    )