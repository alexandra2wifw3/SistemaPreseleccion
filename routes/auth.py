from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash
)
from services.db import get_db, release_db
import bcrypt
auth_bp = Blueprint("auth", __name__)


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verificar_password(password, hash_guardado):
    return bcrypt.checkpw(password.encode(), hash_guardado.encode())

def login_requerido(f):
    """Decorador que protege rutas de reclutador."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "reclutador_id" not in session:
            flash("Debes iniciar sesión primero.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# -- GET /login ----------------------------
@auth_bp.route("/login", methods=["GET"])
def login():
    if "reclutador_id" in session:
        return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


# -- POST /login ----------------------------
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
    release_db(conn)

    if not reclutador or not verificar_password(password, reclutador["password_hash"]):
        flash("Correo o contraseña incorrectos.", "error")
        return render_template("auth/login.html")

    # Guardar sesión
    session["reclutador_id"]     = reclutador["id_reclutador"]
    session["reclutador_nombre"] = reclutador["nombre"]
    session["reclutador_email"]  = reclutador["email"]

    return redirect(url_for("dashboard.index"))


# -- GET /logout ----------------------------
@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("auth.login"))