from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash, jsonify
)
from services.db import get_db
from routes.auth import login_requerido
from datetime import date

vacantes_bp = Blueprint("vacantes", __name__)


# ── GET / — Lista pública de vacantes abiertas ───────────────────
@vacantes_bp.route("/")
def index():
    conn = get_db()
    cur  = conn.cursor()

    # Cerrar automáticamente vacantes vencidas
    cur.execute("""
        UPDATE vacante
        SET estado = 'cerrada'
        WHERE fecha_cierre < CURRENT_DATE
          AND estado = 'abierta'
    """)
    conn.commit()

    # Traer solo las abiertas
    cur.execute("""
        SELECT v.*, r.nombre AS nombre_reclutador,
               COUNT(p.id_postulante) AS total_postulantes
        FROM vacante v
        JOIN reclutador r ON r.id_reclutador = v.id_reclutador
        LEFT JOIN postulante p ON p.id_vacante = v.id_vacante
        WHERE v.estado = 'abierta'
        GROUP BY v.id_vacante, r.nombre
        ORDER BY v.fecha_cierre ASC
    """)
    vacantes = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("public/vacantes.html", vacantes=vacantes)


# ── GET /vacante/<id> — Detalle público de una vacante ───────────
@vacantes_bp.route("/vacante/<int:id_vacante>")
def detalle(id_vacante):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT v.*, r.nombre AS nombre_reclutador
        FROM vacante v
        JOIN reclutador r ON r.id_reclutador = v.id_reclutador
        WHERE v.id_vacante = %s
    """, (id_vacante,))
    vacante = cur.fetchone()
    cur.close()
    conn.close()

    if not vacante:
        return render_template("404.html"), 404

    # Verificar si está expirada
    expirada = vacante["fecha_cierre"] < date.today()

    return render_template(
        "public/formulario.html",
        vacante=vacante,
        expirada=expirada
    )


# ── GET /admin/vacantes — Panel del reclutador ───────────────────
@vacantes_bp.route("/admin/vacantes")
@login_requerido
def admin_vacantes():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT v.*,
               COUNT(p.id_postulante)                          AS total_postulantes,
               COUNT(CASE WHEN p.estado='aprobado'  THEN 1 END) AS aprobados,
               COUNT(CASE WHEN p.estado='rechazado' THEN 1 END) AS rechazados,
               COUNT(CASE WHEN p.estado='pendiente' THEN 1 END) AS pendientes
        FROM vacante v
        LEFT JOIN postulante p ON p.id_vacante = v.id_vacante
        WHERE v.id_reclutador = %s
        GROUP BY v.id_vacante
        ORDER BY v.created_at DESC
    """, (session["reclutador_id"],))
    vacantes = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        "admin/vacantes.html",
        vacantes=vacantes,
        hoy=date.today()
    )


# ── GET /admin/vacante/nueva — Formulario nueva vacante ──────────
@vacantes_bp.route("/admin/vacante/nueva", methods=["GET"])
@login_requerido
def nueva_vacante():
    return render_template("admin/vacante_new.html")


# ── POST /admin/vacante/nueva — Guardar vacante ──────────────────
@vacantes_bp.route("/admin/vacante/nueva", methods=["POST"])
@login_requerido
def nueva_vacante_post():
    titulo       = request.form.get("titulo", "").strip()
    descripcion  = request.form.get("descripcion", "").strip()
    requisitos   = request.form.get("requisitos", "").strip()
    fecha_cierre = request.form.get("fecha_cierre", "")

    if not titulo or not fecha_cierre:
        flash("El título y la fecha de cierre son obligatorios.", "error")
        return render_template("admin/vacante_new.html")

    # Validar que la fecha sea futura
    try:
        fc = date.fromisoformat(fecha_cierre)
        if fc <= date.today():
            flash("La fecha de cierre debe ser futura.", "error")
            return render_template("admin/vacante_new.html")
    except ValueError:
        flash("Fecha inválida.", "error")
        return render_template("admin/vacante_new.html")

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO vacante
            (titulo, descripcion, requisitos, fecha_cierre, id_reclutador)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id_vacante
    """, (titulo, descripcion, requisitos, fecha_cierre,
          session["reclutador_id"]))
    nueva = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    flash(f"Vacante '{titulo}' creada correctamente.", "success")
    return redirect(url_for("vacantes.admin_vacantes"))


# ── POST /admin/vacante/<id>/cerrar — Cerrar manualmente ─────────
@vacantes_bp.route("/admin/vacante/<int:id_vacante>/cerrar",
                   methods=["POST"])
@login_requerido
def cerrar_vacante(id_vacante):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE vacante SET estado = 'cerrada'
        WHERE id_vacante = %s AND id_reclutador = %s
    """, (id_vacante, session["reclutador_id"]))
    conn.commit()
    cur.close()
    conn.close()

    flash("Vacante cerrada. Ya no se aceptan postulaciones.", "info")
    return redirect(url_for("vacantes.admin_vacantes"))