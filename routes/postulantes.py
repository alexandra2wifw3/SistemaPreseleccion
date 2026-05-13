from flask import (
    Blueprint, render_template, request, jsonify
)
from services.db      import get_db
from services.storage import subir_pdf
from services.analisis import consultar_simulador, calcular_score
from services.cv_parser import analizar_cv
from datetime import date
import json

postulantes_bp = Blueprint("postulantes", __name__)


# ── POST /postular/<id_vacante> ──────────────────────────────────
@postulantes_bp.route("/postular/<int:id_vacante>", methods=["POST"])
def postular(id_vacante):
    # ── Obtener datos del formulario ─────────────────────────────
    cedula    = request.form.get("cedula",    "").strip()
    nombres   = request.form.get("nombres",   "").strip()
    apellidos = request.form.get("apellidos", "").strip()
    telefono  = request.form.get("telefono",  "").strip()
    email     = request.form.get("email",     "").strip()
    pdf       = request.files.get("pdf")
    acepta    = request.form.get("acepta_terminos")

    # ── Validaciones básicas ─────────────────────────────────────
    if not acepta:
        return jsonify({
            "error": "Debes aceptar los términos de uso de datos."
        }), 400

    if not cedula or len(cedula) != 10 or not cedula.isdigit():
        return jsonify({"error": "Cédula inválida."}), 400

    if not nombres or not apellidos:
        return jsonify({"error": "Nombres y apellidos son obligatorios."}), 400

    if not pdf or not pdf.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Debes subir un archivo PDF."}), 400

    conn = get_db()
    cur  = conn.cursor()

    # ── Verificar que la vacante existe y está abierta ───────────
    cur.execute("""
        SELECT * FROM vacante
        WHERE id_vacante = %s AND estado = 'abierta'
    """, (id_vacante,))
    vacante = cur.fetchone()

    if not vacante:
        cur.close(); conn.close()
        return jsonify({
            "error": "Esta convocatoria no existe o ya está cerrada."
        }), 404

    # Verificar fecha de cierre en tiempo real
    if vacante["fecha_cierre"] < date.today():
        cur.execute("""
            UPDATE vacante SET estado = 'cerrada'
            WHERE id_vacante = %s
        """, (id_vacante,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({
            "error": "La fecha de postulación ha expirado. "
                     "Espera una nueva convocatoria."
        }), 403

    # ── Verificar que no haya postulado antes ────────────────────
    cur.execute("""
        SELECT id_postulante FROM postulante
        WHERE cedula = %s AND id_vacante = %s
    """, (cedula, id_vacante))
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({
            "error": "Ya existe una postulación con esta cédula "
                     "para esta vacante."
        }), 409

    # ── Subir PDF a Supabase ─────────────────────────────────────
    try:
        pdf_bytes = pdf.read()
        pdf_url   = subir_pdf(cedula, pdf_bytes)
    except Exception as e:
        cur.close(); conn.close()
        return jsonify({"error": f"Error al subir el PDF: {str(e)}"}), 500

    # ── Guardar postulante con estado pendiente ──────────────────
    cur.execute("""
        INSERT INTO postulante
            (cedula, nombres, apellidos, telefono, email,
             archivo_pdf, id_vacante, estado)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendiente')
        RETURNING id_postulante
    """, (cedula, nombres, apellidos, telefono, email,
          pdf_url, id_vacante))
    nuevo = cur.fetchone()
    conn.commit()

    id_postulante = nuevo["id_postulante"]

    # ── Análisis del CV ──────────────────────────────────────────
    resultado_cv = analizar_cv(pdf_url)
    score_cv     = resultado_cv.get("score_cv", 0)

    # ── Consulta al simulador regulatorio ────────────────────────
    datos_simulador = consultar_simulador(cedula)

    # ── Calcular score final ─────────────────────────────────────
    resultado = calcular_score(datos_simulador, score_cv)

    # ── Guardar resultado en resultado_analisis ──────────────────
    cur.execute("""
        INSERT INTO resultado_analisis
            (id_postulante, score_regulatorio, score_cv,
             score_total, licencia_tipo, licencia_estado,
             licencia_puntos, citaciones_pendientes,
             deuda_pendiente, detalle_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        id_postulante,
        resultado["score_regulatorio"],
        resultado["score_cv"],
        resultado["score_total"],
        resultado["licencia_tipo"],
        resultado["licencia_estado"],
        resultado["licencia_puntos"],
        resultado["citaciones_pendientes"],
        resultado["deuda_pendiente"],
        json.dumps({
            **resultado,
            "cv_detalle": resultado_cv.get("desglose_cv", {})
        }, ensure_ascii=False)
    ))

    # ── Actualizar score y estado en postulante ──────────────────
    cur.execute("""
        UPDATE postulante
        SET score_total = %s, estado = %s
        WHERE id_postulante = %s
    """, (resultado["score_total"], resultado["estado"], id_postulante))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "mensaje":  "¡Postulación recibida exitosamente!",
        "cedula":   cedula,
        "nombres":  f"{nombres} {apellidos}",
    })