from flask import Flask, render_template, request, jsonify
from supabase import create_client
import psycopg2, psycopg2.extras, requests, os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require",
                            cursor_factory=psycopg2.extras.RealDictCursor)

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
BUCKET           = "postulantes"
VERIFICACION_URL = os.getenv("VERIFICACION_URL", "http://localhost:5000")


@app.route("/")
def formulario():
    return render_template("formulario.html")

@app.route("/dashboard")
def dashboard():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT p.cedula, pr.nombres, pr.apellidos, p.score, p.estado,
               p.archivo_pdf,
               l.tipo AS tipo_licencia, l.puntos AS puntos_licencia,
               l.estado AS estado_licencia,
               COUNT(c.id_citacion) AS total_citaciones,
               COALESCE(SUM(CASE WHEN c.estado='pendiente' 
                           THEN c.total_pagar ELSE 0 END), 0) AS deuda_pendiente
        FROM postulante p
        JOIN persona pr ON pr.id_persona = p.id_persona
        LEFT JOIN licencia l ON l.id_persona = p.id_persona
        LEFT JOIN citacion c ON c.id_persona = p.id_persona
        GROUP BY p.cedula, pr.nombres, pr.apellidos, p.score, p.estado,
                 p.archivo_pdf, l.tipo, l.puntos, l.estado
        ORDER BY p.score DESC NULLS LAST
    """)
    candidatos = cur.fetchall()
    cur.close(); conn.close()

    total      = len(candidatos)
    aprobados  = sum(1 for c in candidatos if c["estado"] == "aprobado")
    rechazados = sum(1 for c in candidatos if c["estado"] == "rechazado")
    pendientes = sum(1 for c in candidatos if c["estado"] == "pendiente")

    return render_template("dashboard.html", candidatos=candidatos,
                           stats=dict(total=total, aprobados=aprobados,
                                      rechazados=rechazados, pendientes=pendientes))


@app.route("/postular", methods=["POST"])
def postular():
    cedula = request.form.get("cedula", "").strip()
    pdf    = request.files.get("pdf")

    if not cedula or len(cedula) != 10 or not cedula.isdigit():
        return jsonify({"error": "Cédula inválida"}), 400
    if not pdf or not pdf.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Debes subir un archivo PDF"}), 400

    conn = get_db(); cur = conn.cursor()

    # ── ¿Ya postuló? ────────────────────────────────────────────
    cur.execute("SELECT id_postulante FROM postulante WHERE cedula = %s", (cedula,))
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({"error": "Ya existe una postulación con esta cédula"}), 409

    # ── ¿Existe en el sistema regulatorio? ──────────────────────
    cur.execute("SELECT id_persona FROM persona WHERE cedula = %s", (cedula,))
    persona = cur.fetchone()
    if not persona:
        cur.close(); conn.close()
        return jsonify({"error": "Cédula no encontrada en el sistema regulatorio"}), 404

    id_persona = persona["id_persona"]

    # ── Subir PDF a Supabase ─────────────────────────────────────
    nombre_file = f"pdfs/{cedula}.pdf"
    pdf_bytes   = pdf.read()
    try:
        supabase.storage.from_(BUCKET).remove([nombre_file])
    except Exception:
        pass
    supabase.storage.from_(BUCKET).upload(
        nombre_file, pdf_bytes, {"content-type": "application/pdf"}
    )
    pdf_url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{BUCKET}/{nombre_file}"

    # ── Guardar postulante con estado pendiente ──────────────────
    cur.execute("""
        INSERT INTO postulante (cedula, archivo_pdf, estado, id_persona)
        VALUES (%s, %s, 'pendiente', %s)
    """, (cedula, pdf_url, id_persona))
    conn.commit()

    # ── Consulta automática a la simulación AXIS ─────────────────
    datos_axis = consultar_verificacion(cedula)

    # ── Calcular score y actualizar ──────────────────────────────
    score, estado = calcular_score(datos_axis)
    cur.execute("""
        UPDATE postulante SET score = %s, estado = %s WHERE cedula = %s
    """, (score, estado, cedula))
    conn.commit()
    cur.close(); conn.close()

    return jsonify({
        "mensaje": "Postulación recibida y procesada",
        "cedula":  cedula,
        "score":   score,
        "estado":  estado
    })


# ── HELPERS ──────────────────────────────────────────────────────────────────

def consultar_verificacion(cedula):
    try:
        resp = requests.post(
            f"{VERIFICACION_URL}/api/consulta",
            json={"tipo": "cedula", "valor": cedula},   # ← formato correcto
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[verificacion] Error: {e}")
    return {}


def calcular_score(datos):
    score    = 0
    licencia = datos.get("licencia") or {}
    pendientes = datos.get("pendientes") or []

    # Licencia (hasta 40 pts)
    estado_lic = licencia.get("estado", "")
    if estado_lic == "ACTIVA":
        score += 40
    elif estado_lic == "CADUCADA":
        score += 10

    # Puntos de licencia (hasta 30 pts, proporcional sobre 30)
    puntos = int(licencia.get("puntos") or 0)
    score += round((puntos / 30) * 30)

    # Citaciones pendientes (hasta 30 pts, -5 por cada una)
    score += max(0, 30 - len(pendientes) * 5)

    return max(0, min(100, score)), "aprobado" if score >= 60 else "rechazado"


if __name__ == "__main__":
    app.run(debug=True, port=5001)