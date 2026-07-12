import requests as req
import os
from datetime import date, datetime

VERIFICACION_URL = os.getenv(
    "VERIFICACION_URL"
)

# ════════════════════════════════════════════════════════════════
#  CLASIFICACIÓN LEGAL — COIP 2021
#  Fuente: Código Orgánico Integral Penal, febrero 2021
#  https://www.defensa.gob.ec/wp-content/uploads/downloads/2021/03/COIP_act_feb-2021.pdf
# ════════════════════════════════════════════════════════════════

CLASIFICACION_COIP = {
    "muy_grave": {
        "articulos":    ["Art. 383", "Art. 384", "Art. 385"],
        "descripcion":  "Llantas mal estado, sustancias psicotrópicas, embriaguez",
        "puntos_restan": [5, 15, 30],
        "penalizacion_score": 15
    },
    "grave_1": {
        "articulos":    ["Art. 386"],
        "descripcion":  "Primera clase — pena privativa 3 días + multa 1 SBU + 10 puntos",
        "puntos_restan": [10],
        "penalizacion_score": 10
    },
    "grave_2": {
        "articulos":    ["Art. 387"],
        "descripcion":  "Segunda clase — multa 50% SBU + reducción 9 puntos",
        "puntos_restan": [9],
        "penalizacion_score": 9
    },
    "grave_sin_puntos": {
        "articulos":    ["Art. 388", "Art. 389", "Art. 390"],
        "descripcion":  "Tercera, cuarta y quinta clase — multa sin resta de puntos",
        "puntos_restan": [0],
        "penalizacion_score": 5
    },
    "leve": {
        "articulos":    ["Art. 391", "Art. 392"],
        "descripcion":  "Sexta y séptima clase — contravenciones leves",
        "puntos_restan": [0],
        "penalizacion_score": 2
    }
}


def consultar_simulador(cedula):
    """
    Llama al simulador regulatorio con la cédula.
    Retorna el JSON completo o {} si falla.
    """
    try:
        resp = req.post(
            f"{VERIFICACION_URL}/api/consulta",
            json={"tipo": "cedula", "valor": cedula},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[analisis] Error consultando simulador: {e}")
    return {}


def clasificar_infraccion(puntos_restados, nombre_infraccion=""):
    """
    Clasifica la infracción según el COIP 2021 (Arts. 383-392).

    Criterios:
    - 15 o 30 puntos restados  → muy_grave   (Arts. 383-385)
    - 10 puntos restados       → grave_1     (Art. 386)
    - 9  puntos restados       → grave_2     (Art. 387)
    - 0  puntos + arts 388-390 → grave_sin_puntos
    - resto                    → leve        (Arts. 391-392)
    """
    nombre = nombre_infraccion.lower()

    # Muy grave — Arts. 383, 384, 385
    if puntos_restados in [5, 15, 30] and puntos_restados >= 5:
        # Distinguir Art.383 (5pts pero grave) de leves sin puntos
        if puntos_restados >= 15:
            return "muy_grave"
        if puntos_restados == 5:
            # Art.383 llantas = grave, Arts.391-392 leves también usan 5
            if any(k in nombre for k in [
                "llanta", "embriaguez", "estupefaciente",
                "art383", "art384", "art385",
                "art 383", "art 384", "art 385"
            ]):
                return "muy_grave"

    # Grave primera clase — Art. 386 (10 puntos)
    if puntos_restados == 10:
        return "grave_1"

    # Grave segunda clase — Art. 387 (9 puntos)
    if puntos_restados == 9:
        return "grave_2"

    # Grave sin puntos — Arts. 388, 389, 390
    if puntos_restados == 0 and any(k in nombre for k in [
        "art388", "art389", "art390",
        "art 388", "art 389", "art 390",
        "estacionar en zonas peligrosas",
        "adelantar en zonas",
        "apagar el motor",
        "evadir pago",
        "sentido contrario",
        "obstaculizar",
        "desobedecer",
    ]):
        return "grave_sin_puntos"

    # Leve — Arts. 391, 392
    return "leve"


def calcular_score(datos_simulador, score_cv=0):
    """
    Calcula score 0-100 con respaldo en el COIP 2021.

    ┌──────────────────────────────────────────────────────────────┐
    │  CRITERIO               PUNTAJE   BASE LEGAL                │
    ├──────────────────────────────────────────────────────────────┤
    │  Estado de licencia       40 pts  Art. 186 LOTTTSV          │
    │  Puntos de licencia       25 pts  Art. 187 LOTTTSV          │
    │  Citaciones pendientes    20 pts  Arts. 383-392 COIP 2021   │
    │  Deuda pendiente          15 pts  Art. 193 LOTTTSV          │
    ├──────────────────────────────────────────────────────────────┤
    │  SUBTOTAL REGULATORIO    100 pts                            │
    ├──────────────────────────────────────────────────────────────┤
    │  Penalizaciones          variable Arts. 383-392 COIP 2021   │
    │  Bonus CV                 +20 pts análisis hoja de vida     │
    ├──────────────────────────────────────────────────────────────┤
    │  SCORE FINAL              100 pts (con cap)                 │
    └──────────────────────────────────────────────────────────────┘

    Penalizaciones por clase COIP:
    - Muy grave (Arts. 383-385): -15 pts
    - Grave 1ra (Art. 386):      -10 pts
    - Grave 2da (Art. 387):       -9 pts
    - Grave 3ra-5ta (388-390):    -5 pts
    - Leve (Arts. 391-392):       -2 pts
    """
    licencia   = datos_simulador.get("licencia")   or {}
    pendientes = datos_simulador.get("pendientes") or []
    impugnadas = datos_simulador.get("impugnadas") or []
    pagadas    = datos_simulador.get("pagadas")    or []
    anuladas   = datos_simulador.get("anuladas")   or []
    citaciones = datos_simulador.get("citaciones") or []
    deuda      = float(datos_simulador.get("total_pendiente") or 0)

    # -- 1. ESTADO DE LICENCIA (40 pts) ----------------------------
    # Base legal: Art. 186 LOTTTSV — requisito de licencia vigente
    estado_lic = licencia.get("estado", "")

    # Verificar vencimiento real por fecha
    try:
        fecha_exp = licencia.get("fecha_expiracion", "")
        if fecha_exp:
            exp = datetime.strptime(
                str(fecha_exp)[:10], "%Y-%m-%d"
            ).date()
            if exp < date.today() and estado_lic == "ACTIVA":
                estado_lic = "CADUCADA"
    except Exception:
        pass

    if estado_lic == "ACTIVA":
        score_lic = 40
    elif estado_lic == "CADUCADA":
        score_lic = 10   # puede renovar, no descalifica totalmente
    else:
        score_lic = 0    # SUSPENDIDA — inhabilitado legalmente

    # -- 2. PUNTOS DE LICENCIA (25 pts) ----------------------------
    # Base legal: Art. 187 LOTTTSV — sistema de 30 puntos
    puntos_lic = int(licencia.get("puntos") or 0)
    if puntos_lic >= 28:
        score_puntos = 25    # historial casi impecable
    elif puntos_lic >= 23:
        score_puntos = 20    # buen historial
    elif puntos_lic >= 18:
        score_puntos = 14    # historial aceptable
    elif puntos_lic >= 12:
        score_puntos = 8     # historial con observaciones
    elif puntos_lic >= 6:
        score_puntos = 3     # historial preocupante
    else:
        score_puntos = 0     # alto riesgo de suspensión

    # -- 3. CITACIONES PENDIENTES (20 pts) ----------------------------
    # Base legal: Arts. 383-392 COIP 2021
    n_pendientes = len(pendientes)
    if n_pendientes == 0:
        score_cit = 20
    elif n_pendientes == 1:
        score_cit = 12
    elif n_pendientes == 2:
        score_cit = 5
    else:
        score_cit = 0

    # -- 4. DEUDA PENDIENTE (15 pts) ----------------------------
    # Base legal: Art. 193 LOTTTSV — obligación de pago de multas
    if deuda == 0:
        score_deuda = 15
    elif deuda <= 50:
        score_deuda = 10
    elif deuda <= 150:
        score_deuda = 5
    elif deuda <= 300:
        score_deuda = 2
    else:
        score_deuda = 0

    # -- 5. PENALIZACIONES POR CLASE DE INFRACCIÓN (COIP 2021) ----------------------------
    penalizacion     = 0
    infracciones_det = []

    for c in citaciones:
        pts_restados = int(c.get("puntos_perdidos") or 0)
        nombre_inf   = c.get("nombre_contravencion") or ""
        clase        = clasificar_infraccion(pts_restados, nombre_inf)
        pen          = CLASIFICACION_COIP[clase]["penalizacion_score"]

        penalizacion += pen
        infracciones_det.append({
            "nombre":       nombre_inf,
            "clase":        clase,
            "articulo":     CLASIFICACION_COIP[clase]["articulos"][0],
            "penalizacion": pen,
            "estado":       c.get("estado", "")
        })

    # -- Score regulatorio ----------------------------
    score_regulatorio = (
        score_lic + score_puntos + score_cit + score_deuda
    )
    score_regulatorio = max(0, score_regulatorio - penalizacion)
    score_regulatorio = min(100, score_regulatorio)

    # -- Score final con bonus CV ----------------------------
    score_cv_aplicado = min(int(score_cv), 20)
    score_total       = min(100, score_regulatorio + score_cv_aplicado)
    estado            = "aprobado" if score_total >= 60 else "rechazado"

    return {
        # ── Resultado final ----------------------------
        "score_regulatorio":      score_regulatorio,
        "score_cv":               score_cv_aplicado,
        "score_total":            score_total,
        "estado":                 estado,

        # -- Datos de licencia ----------------------------
        "licencia_tipo":          licencia.get("tipo", "—"),
        "licencia_estado":        estado_lic or "—",
        "licencia_puntos":        puntos_lic,

        # -- Datos de citaciones ----------------------------
        "citaciones_pendientes":  n_pendientes,
        "citaciones_impugnadas":  len(impugnadas),
        "citaciones_pagadas":     len(pagadas),
        "citaciones_anuladas":    len(anuladas),
        "deuda_pendiente":        deuda,
        "penalizacion_total":     penalizacion,

        # -- Desglose para dashboard ----------------------------
        "desglose": {
            "licencia":     score_lic,
            "puntos":       score_puntos,
            "citaciones":   score_cit,
            "deuda":        score_deuda,
            "penalizacion": -penalizacion,
            "bonus_cv":     score_cv_aplicado,
        },

        # -- Detalle de cada infracción clasificada ----------------------------
        "infracciones": infracciones_det,

        # -- Base legal  ----------------------------
        "base_legal": {
            "licencia":  "Art. 186 LOTTTSV — requisito licencia vigente",
            "puntos":    "Art. 187 LOTTTSV — sistema de puntos (máx. 30)",
            "muy_grave": "Arts. 383-385 COIP 2021 — llantas, sustancias, embriaguez",
            "grave_1":   "Art. 386 COIP 2021 — contravención primera clase",
            "grave_2":   "Art. 387 COIP 2021 — contravención segunda clase",
            "grave_3_5": "Arts. 388-390 COIP 2021 — tercera a quinta clase",
            "leve":      "Arts. 391-392 COIP 2021 — sexta y séptima clase",
            "fuente":    "https://www.defensa.gob.ec/wp-content/uploads/downloads/2021/03/COIP_act_feb-2021.pdf"
        }
    }