from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, jsonify
)
from services.db import get_db, release_db
from services.analisis import consultar_simulador, calcular_score
from services.cv_parser import analizar_cv, CV_IA_DELAY_SEGUNDOS
from routes.auth      import login_requerido
from datetime import date
import json
import time

dashboard_bp = Blueprint("dashboard", __name__)


# -- GET /reclutador — Panel principal ----------------------------
@dashboard_bp.route("/reclutador")
@dashboard_bp.route("/reclutador/dashboard")
@login_requerido
def index():
    conn = get_db()
    cur  = conn.cursor()

    # Resumen general de todas las vacantes del reclutador
    cur.execute("""
        SELECT
            COUNT(DISTINCT v.id_vacante)                        AS total_vacantes,
            COUNT(p.id_postulante)                              AS total_postulantes,
            COUNT(CASE WHEN p.estado = 'aprobado'  THEN 1 END) AS aprobados,
            COUNT(CASE WHEN p.estado = 'rechazado' THEN 1 END) AS rechazados,
            COUNT(CASE WHEN p.estado = 'pendiente' THEN 1 END) AS pendientes
        FROM vacante v
        LEFT JOIN postulante p ON p.id_vacante = v.id_vacante
        WHERE v.id_reclutador = %s
    """, (session["reclutador_id"],))
    stats = cur.fetchone()

    # Últimas vacantes
    cur.execute("""
        SELECT v.*,
               COUNT(p.id_postulante) AS total_postulantes
        FROM vacante v
        LEFT JOIN postulante p ON p.id_vacante = v.id_vacante
        WHERE v.id_reclutador = %s
        GROUP BY v.id_vacante
        ORDER BY v.created_at DESC
        LIMIT 5
    """, (session["reclutador_id"],))
    vacantes = cur.fetchall()

    cur.close()
    release_db(conn)

    return render_template(
        "reclutador/dashboard.html",
        stats=stats,
        vacantes=vacantes,
        hoy=date.today()
    )


# -- GET /reclutador/vacante/<id>/resultados — Ranking de candidatos ----------------------------
@dashboard_bp.route("/reclutador/vacante/<int:id_vacante>/resultados")
@login_requerido
def resultados(id_vacante):
    conn = get_db()
    cur  = conn.cursor()

    # Verificar que la vacante pertenece al reclutador
    cur.execute("""
        SELECT * FROM vacante
        WHERE id_vacante = %s AND id_reclutador = %s
    """, (id_vacante, session["reclutador_id"]))
    vacante = cur.fetchone()

    if not vacante:
        cur.close(); release_db(conn)
        return render_template("404.html"), 404

    # Ranking de postulantes ordenado por score
    cur.execute("""
        SELECT
            p.*,
            r.score_regulatorio,
            r.score_cv,
            r.score_total,
            r.licencia_tipo,
            r.licencia_estado,
            r.licencia_puntos,
            r.citaciones_pendientes,
            r.deuda_pendiente,
            r.detalle_json,
            r.procesado_at
        FROM postulante p
        LEFT JOIN resultado_analisis r
               ON r.id_postulante = p.id_postulante
        WHERE p.id_vacante = %s
        ORDER BY r.score_total DESC NULLS LAST,
                 p.created_at ASC
    """, (id_vacante,))
    candidatos = cur.fetchall()

    # Estadísticas del ranking
    total      = len(candidatos)
    aprobados  = sum(1 for c in candidatos if c["estado"] == "aprobado")
    rechazados = sum(1 for c in candidatos if c["estado"] == "rechazado")
    pendientes = sum(1 for c in candidatos if c["estado"] == "pendiente")

    # Promedio de score
    scores = [c["score_total"] for c in candidatos if c["score_total"]]
    promedio = round(sum(scores) / len(scores), 1) if scores else 0

    stats = {
        "total":      total,
        "aprobados":  aprobados,
        "rechazados": rechazados,
        "pendientes": pendientes,
        "promedio":   promedio,
    }

    cur.close()
    release_db(conn)

    return render_template(
        "reclutador/candidatos.html",
        vacante=vacante,
        candidatos=candidatos,
        stats=stats,
        mejor=candidatos[0] if candidatos else None
    )


# -- GET /reclutador/candidato/<id> — Detalle de un candidato ----------------------------
@dashboard_bp.route("/reclutador/candidato/<int:id_postulante>")
@login_requerido
def detalle_candidato(id_postulante):
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT p.*,
               r.score_regulatorio, r.score_cv, r.score_total,
               r.licencia_tipo, r.licencia_estado, r.licencia_puntos,
               r.citaciones_pendientes, r.deuda_pendiente,
               r.detalle_json, r.procesado_at
        FROM postulante p
        LEFT JOIN resultado_analisis r
               ON r.id_postulante = p.id_postulante
        WHERE p.id_postulante = %s
    """, (id_postulante,))
    candidato = cur.fetchone()
    cur.close()
    release_db(conn)

    if not candidato:
        return render_template("404.html"), 404

    # Parsear el JSON del detalle
    detalle = {}
    if candidato["detalle_json"]:
        try:
            detalle = json.loads(candidato["detalle_json"])
        except Exception:
            detalle = {}

    return render_template(
        "reclutador/detalle_candidato.html",
        candidato=candidato,
        detalle=detalle
    )


# -- POST /reclutador/vacante/<id>/procesar — Procesar pendientes ----------------------------
# Se activa manualmente cuando el reclutador quiere re-analizar
@dashboard_bp.route(
    "/reclutador/vacante/<int:id_vacante>/procesar",
    methods=["POST"]
)
@login_requerido
def procesar_pendientes(id_vacante):
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT id_postulante, cedula, archivo_pdf
        FROM postulante
        WHERE id_vacante = %s AND estado = 'pendiente'
    """, (id_vacante,))
    pendientes = cur.fetchall()

    procesados = 0
    for p in pendientes:
        try:
            resultado_cv    = analizar_cv(p["archivo_pdf"])
            score_cv        = resultado_cv.get("score_cv", 0)
            datos_simulador = consultar_simulador(p["cedula"])
            resultado       = calcular_score(datos_simulador, score_cv)

            # Guardar resultado
            cur.execute("""
                INSERT INTO resultado_analisis
                    (id_postulante, score_regulatorio, score_cv,
                     score_total, licencia_tipo, licencia_estado,
                     licencia_puntos, citaciones_pendientes,
                     deuda_pendiente, detalle_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id_postulante)
                DO UPDATE SET
                    score_regulatorio  = EXCLUDED.score_regulatorio,
                    score_cv           = EXCLUDED.score_cv,
                    score_total        = EXCLUDED.score_total,
                    licencia_tipo      = EXCLUDED.licencia_tipo,
                    licencia_estado    = EXCLUDED.licencia_estado,
                    licencia_puntos    = EXCLUDED.licencia_puntos,
                    citaciones_pendientes = EXCLUDED.citaciones_pendientes,
                    deuda_pendiente    = EXCLUDED.deuda_pendiente,
                    detalle_json       = EXCLUDED.detalle_json,
                    procesado_at       = CURRENT_TIMESTAMP
            """, (
                p["id_postulante"],
                resultado["score_regulatorio"],
                resultado["score_cv"],
                resultado["score_total"],
                resultado["licencia_tipo"],
                resultado["licencia_estado"],
                resultado["licencia_puntos"],
                resultado["citaciones_pendientes"],
                resultado["deuda_pendiente"],
                json.dumps(resultado, ensure_ascii=False)
            ))

            cur.execute("""
                UPDATE postulante
                SET score_total = %s, estado = %s
                WHERE id_postulante = %s
            """, (resultado["score_total"],
                  resultado["estado"],
                  p["id_postulante"]))

            procesados += 1

        except Exception as e:
            print(f"[dashboard] Error procesando {p['cedula']}: {e}")
            continue

    conn.commit()
    cur.close()
    release_db(conn)

    return jsonify({
        "mensaje":    f"{procesados} postulantes procesados.",
        "procesados": procesados
    })