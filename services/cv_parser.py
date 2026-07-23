import pdfplumber
import requests as req
import tempfile
import os
import re
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Pausa entre llamadas a Gemini al procesar un lote de postulantes,
# para no saturar el límite de peticiones por minuto del free tier.
CV_IA_DELAY_SEGUNDOS = float(os.getenv("CV_IA_DELAY_SEGUNDOS", "3"))

_gemini_client = None

# ════════════════════════════════════════════════════════════════
#  CV PARSER — Análisis de Hoja de Vida
#  Orientado a conductores profesionales para empresas de flotas
#  Base legal: Reglamento a la LOTTTSV — tipos de licencia
# ════════════════════════════════════════════════════════════════

# -- Tipos de licencia profesional según LOTTTSV ----------------------------
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

# -- Experiencia en conducción profesional ----------------------------
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

# -- Años de experiencia (mínimo 2 años para flotas) ----------------------------
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

# -- Formación y certificaciones relevantes ----------------------------
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

# -- Referencias laborales en transporte ----------------------------
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


def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no está configurada en .env")
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


ESQUEMA_EXTRACCION_CV = {
    "type": "object",
    "properties": {
        "licencia_detectada": {
            "type": "string",
            "enum": ["E", "D", "C", "A1", "G", "NINGUNA"],
            "description": "Tipo de licencia profesional de conducción más alta mencionada en el CV. NINGUNA si no se menciona ninguna."
        },
        "anios_experiencia": {
            "type": "integer",
            "description": "Años de experiencia en conducción profesional mencionados o inferidos del CV. 0 si no hay información."
        },
        "conceptos_experiencia_flota": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Subconjunto de la lista de conceptos de experiencia en flotas que el CV menciona o implica, aunque use otras palabras."
        },
        "conceptos_formacion": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Subconjunto de la lista de conceptos de formación/certificaciones que el CV menciona o implica, aunque use otras palabras."
        },
        "cedula_en_cv": {
            "type": "string",
            "description": "Número de cédula ecuatoriana (10 dígitos) encontrado en el CV, como texto. Cadena vacía si no aparece ninguna."
        }
    },
    "required": [
        "licencia_detectada", "anios_experiencia",
        "conceptos_experiencia_flota", "conceptos_formacion", "cedula_en_cv"
    ]
}


def extraer_datos_cv_ia(texto):
    """
    Usa Gemini para extraer del CV los mismos datos que antes se buscaban
    por coincidencia literal de palabras, pero de forma semántica —
    tolera CVs con formato o redacción distintos a la plantilla esperada.
    """
    client = get_gemini_client()

    prompt = f"""Eres un extractor de datos de hojas de vida (CV) de conductores profesionales.
Analiza el siguiente texto de un CV y extrae la información solicitada en el esquema JSON.

Lista de conceptos de EXPERIENCIA EN FLOTAS a buscar (marca solo los que el CV
menciona o implica claramente, sin inventar):
{json.dumps(KEYWORDS_EXPERIENCIA, ensure_ascii=False)}

Lista de conceptos de FORMACIÓN/CERTIFICACIONES a buscar (mismo criterio):
{json.dumps(KEYWORDS_FORMACION, ensure_ascii=False)}

Texto del CV:
---
{texto[:8000]}
---
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ESQUEMA_EXTRACCION_CV,
        ),
    )
    return json.loads(response.text)


def _score_desde_extraccion_ia(datos):
    """
    Convierte los datos extraídos por la IA en los mismos puntajes 0-20
    definidos por la tabla de reglas del proyecto (ver analizar_cv).
    """
    tipo_lic = datos.get("licencia_detectada") or "NINGUNA"
    tipo_lic = None if tipo_lic == "NINGUNA" else tipo_lic
    pts_licencia = LICENCIAS_PROFESIONALES[tipo_lic]["peso"] if tipo_lic in LICENCIAS_PROFESIONALES else 0

    anios = int(datos.get("anios_experiencia") or 0)
    if anios >= 6:
        pts_experiencia = 6
    elif anios >= 3:
        pts_experiencia = 4
    elif anios >= 1:
        pts_experiencia = 2
    else:
        pts_experiencia = 0

    n_flota = len(datos.get("conceptos_experiencia_flota") or [])
    if n_flota >= 3:
        pts_flota = 4
    elif n_flota >= 2:
        pts_flota = 3
    elif n_flota >= 1:
        pts_flota = 2
    else:
        pts_flota = 0

    n_formacion = len(datos.get("conceptos_formacion") or [])
    if n_formacion >= 3:
        pts_formacion = 4
    elif n_formacion >= 2:
        pts_formacion = 3
    elif n_formacion >= 1:
        pts_formacion = 2
    else:
        pts_formacion = 0

    return tipo_lic, pts_licencia, pts_experiencia, pts_flota, pts_formacion


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

    # -- Detecciones: primero IA (Gemini), con respaldo por keywords ----------
    metodo = "ia"
    cedula_en_cv = None
    try:
        datos_ia = extraer_datos_cv_ia(texto)
        tipo_lic, pts_licencia, pts_experiencia, pts_flota, pts_formacion = \
            _score_desde_extraccion_ia(datos_ia)
        cedula_en_cv = datos_ia.get("cedula_en_cv") or None
    except Exception as e:
        print(f"[cv_parser] Gemini no disponible, usando fallback por keywords: {e}")
        metodo = "keywords"
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
        "score_cv":     score_cv,
        "licencia_cv":  tipo_lic,
        "cedula_en_cv": cedula_en_cv,
        "metodo":       metodo,
        "detalle":     f"Licencia {tipo_lic or 'no detectada'} · "
                       f"{pts_experiencia} pts experiencia · "
                       f"{pts_flota} pts flota · "
                       f"{pts_formacion} pts formación · "
                       f"(método: {metodo})",
        "desglose_cv": {
            "licencia_detectada": tipo_lic,
            "pts_licencia":       pts_licencia,
            "pts_experiencia":    pts_experiencia,
            "pts_flota":          pts_flota,
            "pts_formacion":      pts_formacion,
            "score_bruto":        score_bruto,
            "score_aplicado":     score_cv,
            "metodo":             metodo,
        }
    }