from flask import (
    Blueprint, render_template, request, jsonify, session
)
from routes.auth import login_requerido
from services.db      import get_db
from services.storage import subir_pdf
from datetime import date
import traceback

postulantes_bp = Blueprint("postulantes", __name__)


# -- POST /postular/<id_vacante> ------------------------------------------
@postulantes_bp.route("/postular/<int:id_vacante>", methods=["POST"])
def postular(id_vacante):
    cedula    = request.form.get("cedula",    "").strip()
    nombres   = request.form.get("nombres",   "").strip()
    apellidos = request.form.get("apellidos", "").strip()
    telefono  = request.form.get("telefono",  "").strip()
    email     = request.form.get("email",     "").strip()
    pdf       = request.files.get("pdf")
    acepta    = request.form.get("acepta_terminos")

    # -- Validaciones básicas ----------------------------------------------
    if not acepta:
        return jsonify({"error": "Debes aceptar los términos de uso de datos."}), 400
    if not cedula or len(cedula) != 10 or not cedula.isdigit():
        return jsonify({"error": "Cédula inválida. Debe tener exactamente 10 dígitos."}), 400
    if not nombres or not apellidos:
        return jsonify({"error": "Nombres y apellidos son obligatorios."}), 400
    if not pdf or not pdf.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Debes subir un archivo PDF válido."}), 400

    conn = get_db()
    cur  = conn.cursor()

    try:
        # -- Verificar que la vacante existe y está abierta ----------------
        cur.execute("""
            SELECT * FROM vacante
            WHERE id_vacante = %s AND estado = 'abierta'
        """, (id_vacante,))
        vacante = cur.fetchone()

        if not vacante:
            return jsonify({"error": "Esta convocatoria no existe o ya está cerrada."}), 404

        if vacante["fecha_cierre"] < date.today():
            cur.execute(
                "UPDATE vacante SET estado='cerrada' WHERE id_vacante=%s",
                (id_vacante,)
            )
            conn.commit()
            return jsonify({"error": "La fecha de postulación ha expirado."}), 403

        # -- Verificar postulación duplicada --------------------------------
        cur.execute("""
            SELECT id_postulante FROM postulante
            WHERE cedula = %s AND id_vacante = %s
        """, (cedula, id_vacante))
        if cur.fetchone():
            return jsonify({"error": "Ya existe una postulación con esta cédula para esta vacante."}), 409

        # -- Subir PDF a Supabase ------------------------------------------
        try:
            pdf_bytes = pdf.read()
            pdf_url   = subir_pdf(cedula, pdf_bytes)
        except Exception as e:
            print(f"[postular] Error subiendo PDF: {e}")
            traceback.print_exc()
            return jsonify({"error": f"Error al subir el archivo: {str(e)}"}), 500

        # -- Guardar postulante en BD --------------------------------------
        cur.execute("""
            INSERT INTO postulante
                (cedula, nombres, apellidos, telefono, email,
                 archivo_pdf, id_vacante, estado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendiente')
            RETURNING id_postulante
        """, (cedula, nombres, apellidos, telefono, email, pdf_url, id_vacante))
        conn.commit()

        return jsonify({
            "mensaje": "¡Postulación recibida exitosamente!",
            "cedula":  cedula,
            "nombres": f"{nombres} {apellidos}",
        })

    except Exception as e:
        conn.rollback()
        print(f"[postular] Error inesperado: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Error inesperado: {str(e)}"}), 500

    finally:
        cur.close()
        release_db(conn)


# -- GET /reclutador/vacante/<id>/postulantes -----------------------------
@postulantes_bp.route("/reclutador/vacante/<int:id_vacante>/postulantes")
@login_requerido
def admin_postulantes(id_vacante):
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT * FROM vacante WHERE id_vacante = %s AND id_reclutador = %s
    """, (id_vacante, session["reclutador_id"]))
    vacante = cur.fetchone()

    if not vacante:
        cur.close(); release_db(conn)
        return render_template("404.html"), 404

    cur.execute("""
        SELECT p.*, r.score_total, r.score_regulatorio, r.score_cv,
               r.licencia_tipo, r.licencia_estado, r.licencia_puntos,
               r.citaciones_pendientes, r.deuda_pendiente
        FROM postulante p
        LEFT JOIN resultado_analisis r ON r.id_postulante = p.id_postulante
        WHERE p.id_vacante = %s
        ORDER BY r.score_total DESC NULLS LAST
    """, (id_vacante,))
    postulantes = cur.fetchall()

    cur.close(); release_db(conn)

    return render_template(
        "reclutador/postulantes.html",
        vacante=vacante,
        postulantes=postulantes
    )