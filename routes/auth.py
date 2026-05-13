from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash
)
from services.db import get_db
import hashlib

auth_bp = Blueprint("auth", __name__)


def hash_password(password):
    """SHA-256 simple. En producción usar bcrypt."""
    return hashlib.sha256(password.encode()).hexdigest()


def login_requerido(f):
    """Decorador que protege rutas de admin."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "reclutador_id" not in session:
            flash("Debes iniciar sesión primero.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ── GET /login ───────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET"])
def login():
    if "reclutador_id" in session:
        return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


# ── POST /login ──────────────────────────────────────────────────
@auth_bp.route("/login", methods=["POST"])
def login_post():
    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Completa todos los campos.", "error")
        return render_template("auth/login.html")

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM reclutador WHERE email = %s",
        (email,)
    )
    reclutador = cur.fetchone()
    cur.close()
    conn.close()

    if not reclutador or reclutador["password_hash"] != hash_password(password):
        flash("Correo o contraseña incorrectos.", "error")
        return render_template("auth/login.html")

    # Guardar sesión
    session["reclutador_id"]     = reclutador["id_reclutador"]
    session["reclutador_nombre"] = reclutador["nombre"]
    session["reclutador_email"]  = reclutador["email"]

    return redirect(url_for("dashboard.index"))


# ── GET /logout ──────────────────────────────────────────────────
@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("auth.login"))


# ── GET /registro (solo para crear el primer reclutador) ─────────
# IMPORTANTE: deshabilitar en producción real
@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nombre   = request.form.get("nombre", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not nombre or not email or not password:
            flash("Completa todos los campos.", "error")
            return render_template("auth/registro.html")

        conn = get_db()
        cur  = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO reclutador (nombre, email, password_hash)
                VALUES (%s, %s, %s)
            """, (nombre, email, hash_password(password)))
            conn.commit()
            flash("Reclutador creado correctamente.", "success")
            return redirect(url_for("auth.login"))
        except Exception:
            conn.rollback()
            flash("El correo ya está registrado.", "error")
            return render_template("auth/registro.html")
        finally:
            cur.close()
            conn.close()

    return render_template("auth/registro.html")