from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash
)
from services.db import get_db
from functools import wraps
import bcrypt

admin_bp = Blueprint("administrador", __name__)

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def admin_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_id" not in session:
            flash("Acceso restringido.", "warning")
            return redirect(url_for("administrador.login"))
        return f(*args, **kwargs)
    return decorated

# -- Login admin ----------------------------
@admin_bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if "admin_id" in session:
        return redirect(url_for("administrador.panel"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT * FROM administrador WHERE email = %s", (email,))
        admin = cur.fetchone()
        cur.close(); conn.close()

        if not admin or not bcrypt.checkpw(password.encode(), admin["password_hash"].encode()):
            flash("Credenciales incorrectas.", "error")
            return render_template("admin/login-admin.html")

        session["admin_id"]     = admin["id_admin"]
        session["admin_nombre"] = admin["nombre"]
        return redirect(url_for("administrador.panel"))

    return render_template("admin/login-admin.html")

# -- Logout admin ----------------------------
@admin_bp.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("administrador.login"))

# -- Panel admin ----------------------------
@admin_bp.route("/admin/panel")
@admin_requerido
def panel():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id_reclutador, nombre, email, created_at FROM reclutador ORDER BY created_at DESC")
    reclutadores = cur.fetchall()
    cur.close(); conn.close()
    return render_template("admin/panel.html", reclutadores=reclutadores)

# -- Crear reclutador ----------------------------
@admin_bp.route("/admin/reclutadores/nuevo", methods=["GET", "POST"])
@admin_requerido
def nuevo_reclutador():
    if request.method == "POST":
        nombre   = request.form.get("nombre", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not nombre or not email or not password:
            flash("Completa todos los campos.", "error")
            return render_template("admin/nuevo-reclutador.html")

        conn = get_db()
        cur  = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO reclutador (nombre, email, password_hash)
                VALUES (%s, %s, %s)
            """, (nombre, email, hash_password(password)))
            conn.commit()
            flash(f"Reclutador {nombre} creado correctamente.", "success")
            return redirect(url_for("administrador.panel"))
        except Exception:
            conn.rollback()
            flash("El correo ya está registrado.", "error")
            return render_template("admin/nuevo-reclutador.html")
        finally:
            cur.close(); conn.close()

    return render_template("admin/nuevo-reclutador.html")

# -- Eliminar reclutador ----------------------------
@admin_bp.route("/admin/reclutadores/<int:id>/eliminar", methods=["POST"])
@admin_requerido
def eliminar_reclutador(id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM reclutador WHERE id_reclutador = %s", (id,))
    conn.commit()
    cur.close(); conn.close()
    flash("Reclutador eliminado.", "info")
    return redirect(url_for("administrador.panel"))