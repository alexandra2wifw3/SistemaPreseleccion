import pdfplumber
import requests as req
import tempfile
import os
import re

# ════════════════════════════════════════════════════════════════
#  CV PARSER — Análisis de Hoja de Vida
#  Orientado a conductores profesionales para empresas de flotas
#  Base legal: Reglamento a la LOTTTSV — tipos de licencia
# ════════════════════════════════════════════════════════════════

# ── Tipos de licencia profesional según LOTTTSV ──────────────────
# Fuente: https://www.ant.gob.ec/licencias-de-conducir
LICENCIAS_PROFESIONALES = {
    "E": {
        "descripcion": "Camiones pesados, tráiler, volquetas, tanqueros >3.5t",
        "peso":        20,    # máximo puntaje — más exigente para flotas pesadas
        "keywords":    [
            "licencia tipo e", "licencia e", "tipo e",
            "camión pesado", "trailer", "tracto camión",
            "volqueta", "tanquero", "plataforma",
            "licencia e profesional"
        ]
    },
    "D": {
        "descripcion": "Buses interprovinciales, intracantonales >26 asientos",
        "peso":        18,
        "keywords":    [
            "licencia tipo d", "licencia d", "tipo d",
            "bus interprovincial", "bus intraprovincial",
            "transporte de pasajeros", "conductor de bus",
            "licencia d profesional"
        ]
    },
    "C": {
        "descripcion": "Taxis, camionetas hasta 3500kg, hasta 25 pasajeros",
        "peso":        14,
        "keywords":    [
            "licencia tipo c", "licencia c", "tipo c",
            "taxi ejecutivo", "taxi convencional",
            "camioneta liviana", "transporte liviano",
            "licencia c profesional"
        ]
    },
    "A1": {
        "descripcion": "Motocicletas, tricimotos de servicio comercial",
        "peso":        8,
        "keywords":    [
            "licencia tipo a1", "licencia a1", "tipo a1",
            "motocicleta comercial", "trimoto", "ciclomotor"
        ]
    },
    "G": {
        "descripcion": "Maquinaria pesada, agrícola, equipos camineros",
        "peso":        10,
        "keywords":    [
            "licencia tipo g", "licencia g", "tipo g",
            "maquinaria pesada", "maquinaria agrícola",
            "retroexcavadora", "montacargas", "tractor",
            "motoniveladora"
        ]
    }
}

# ── Experiencia en conducción profesional ─────────────────────────
KEYWORDS_EXPERIENCIA = [
    "conductor profesional", "chofer profesional",
    "conductor de flota", "operador de flota",
    "transporte de carga", "transporte de pasajeros",
    "distribución y logística", "logística de transporte",
    "operador de vehículos pesados", "conductor de camión",
    "conductor de bus", "conductor de trailer",
    "manejo defensivo", "conducción defensiva",
    "operador logístico", "flota vehicular",
    "transporte empresarial", "rutas de transporte"
]

# ── Años de experiencia (mínimo 2 años para flotas) ──────────────
KEYWORDS_ANIOS_EXPERIENCIA = {
    "alta":  [
        "10 años", "9 años", "8 años", "7 años", "6 años",
        "más de 5 años", "más de 8 años", "más de 10 años"
    ],
    "media": [
        "5 años", "4 años", "3 años", "2 años",
        "más de 2 años", "más de 3 años"
    ],
    "baja":  [
        "1 año", "6 meses", "1 año de experiencia"
    ]
}

# ── Formación y certificaciones relevantes ────────────────────────
KEYWORDS_FORMACION = [
    "manejo defensivo", "conducción defensiva",
    "primeros auxilios", "seguridad vial",
    "transporte de materiales peligrosos",
    "certificado de conductor", "curso de conducción",
    "tecnólogo en transporte", "logística y transporte",
    "seguridad industrial", "prevención de riesgos",
    "operación de maquinaria", "mecánica básica",
    "gps y telemetría", "tacógrafo"
]

# ── Referencias laborales en transporte ──────────────────────────
KEYWORDS_REFERENCIAS = [
    "empresa de transporte", "compañía de transporte",
    "cooperativa de transporte", "flota de vehículos",
    "empresa logística", "operadora de transporte",
    "municipio", "ministerio de transporte"
]


def extraer_texto_pdf(pdf_url):
    """
    Descargar el PDF desde Supabase y extrae todo el texto.
    Retorna el texto en minúsculas o cadena vacía si falla.
    """
    try:
        resp = req.get(pdf_url, timeout=15)
        resp.raise_for_status()

        with tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False
        ) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        with pdfplumber.open(tmp_path) as pdf:
            texto = " ".join(
                pagina.extract_text() or ""
                for pagina in pdf.pages
            ).lower()

        os.unlink(tmp_path)
        return texto

    except Exception as e:
        print(f"[cv_parser] Error extrayendo PDF: {e}")
        return ""


def detectar_licencia(texto):
    """
    Detecta el tipo de licencia profesional mencionada en el CV.
    Retorna (tipo, puntaje) del tipo más alto encontrado.
    """
    # Orden de prioridad para flotas: E > D > C > G > A1
    orden_prioridad = ["E", "D", "C", "G", "A1"]

    for tipo in orden_prioridad:
        datos = LICENCIAS_PROFESIONALES[tipo]
        if any(kw in texto for kw in datos["keywords"]):
            return tipo, datos["peso"]

    return None, 0


def detectar_experiencia(texto):
    """
    Detecta años de experiencia en conducción profesional.
    Retorna puntaje según nivel encontrado.
    """
    # Buscar años con expresión regular primero
    # Patrones: "10 años de experiencia", "experiencia de 5 años"
    patron = re.search(
        r'(\d+)\s*años?\s*(de\s*)?(experiencia|conducción|manejo)',
        texto
    )
    if patron:
        anios = int(patron.group(1))
        if anios >= 6:
            return 6    # experiencia alta
        elif anios >= 3:
            return 4    # experiencia media
        elif anios >= 1:
            return 2    # experiencia básica
        return 0

    # Si no hay número, buscar por keywords
    for kw in KEYWORDS_ANIOS_EXPERIENCIA["alta"]:
        if kw in texto:
            return 6
    for kw in KEYWORDS_ANIOS_EXPERIENCIA["media"]:
        if kw in texto:
            return 4
    for kw in KEYWORDS_ANIOS_EXPERIENCIA["baja"]:
        if kw in texto:
            return 2

    return 0


def detectar_experiencia_flota(texto):
    """
    Detecta si tiene experiencia específica en flotas empresariales.
    Retorna puntaje 0-4.
    """
    encontrados = sum(
        1 for kw in KEYWORDS_EXPERIENCIA if kw in texto
    )
    if encontrados >= 3:
        return 4
    elif encontrados >= 2:
        return 3
    elif encontrados >= 1:
        return 2
    return 0


def detectar_formacion(texto):
    """
    Detecta formación y certificaciones relevantes.
    Retorna puntaje 0-4.
    """
    encontrados = sum(
        1 for kw in KEYWORDS_FORMACION if kw in texto
    )
    if encontrados >= 3:
        return 4
    elif encontrados >= 2:
        return 3
    elif encontrados >= 1:
        return 2
    return 0


def analizar_cv(pdf_url):
    """
    Analiza el CV y retorna score de 0 a 20 con desglose.

    ┌─────────────────────────────────────────────────────────────┐
    │  CRITERIO CV              PUNTAJE  DESCRIPCIÓN             │
    ├─────────────────────────────────────────────────────────────┤
    │  Tipo de licencia          0-20    E=20, D=18, C=14, G=10  │
    │  Años de experiencia       0-6     ≥6años=6, ≥3=4, ≥1=2   │
    │  Experiencia en flotas     0-4     keywords específicos     │
    │  Formación / certificados  0-4     cursos relevantes        │
    ├─────────────────────────────────────────────────────────────┤
    │  TOTAL (con cap a 20)      0-20                            │
    └─────────────────────────────────────────────────────────────┘

    Nota: el puntaje máximo real puede superar 20 (ej: E+6+4+4=34)
    pero se aplica cap en 20 para no distorsionar el score total.
    """
    texto = extraer_texto_pdf(pdf_url)

    if not texto:
        return {
            "score_cv":      0,
            "detalle":       "No se pudo extraer texto del PDF",
            "licencia_cv":   None,
            "desglose_cv":   {}
        }

    # ── Detecciones ───────────────────────────────────────────────
    tipo_lic, pts_licencia   = detectar_licencia(texto)
    pts_experiencia          = detectar_experiencia(texto)
    pts_flota                = detectar_experiencia_flota(texto)
    pts_formacion            = detectar_formacion(texto)

    score_bruto = (
        pts_licencia +
        pts_experiencia +
        pts_flota +
        pts_formacion
    )
    score_cv = min(score_bruto, 20)   # cap en 20

    return {
        "score_cv":    score_cv,
        "licencia_cv": tipo_lic,
        "detalle":     f"Licencia {tipo_lic or 'no detectada'} · "
                       f"{pts_experiencia} pts experiencia · "
                       f"{pts_flota} pts flota · "
                       f"{pts_formacion} pts formación",
        "desglose_cv": {
            "licencia_detectada": tipo_lic,
            "pts_licencia":       pts_licencia,
            "pts_experiencia":    pts_experiencia,
            "pts_flota":          pts_flota,
            "pts_formacion":      pts_formacion,
            "score_bruto":        score_bruto,
            "score_aplicado":     score_cv,
        }
    }