from supabase import create_client
import os

BUCKET = "postulantes"
_supabase = None

def get_supabase():
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL y SUPABASE_KEY deben estar en .env")
        _supabase = create_client(url, key)
    return _supabase


def subir_pdf(cedula, pdf_bytes):
    """
    Sube el PDF a Supabase Storage.
    Retorna la URL pública del archivo.
    """
    supabase    = get_supabase()
    nombre_file = f"pdfs/{cedula}.pdf"

    # Intentar eliminar el anterior si existe
    try:
        supabase.storage.from_(BUCKET).remove([nombre_file])
    except Exception:
        pass  # no importa si no existía

    # Subir el nuevo
    resultado = supabase.storage.from_(BUCKET).upload(
        nombre_file,
        pdf_bytes,
        {"content-type": "application/pdf", "upsert": "true"}
    )

    # Verificar que subió correctamente
    if hasattr(resultado, 'error') and resultado.error:
        raise Exception(f"Error Supabase: {resultado.error}")

    pdf_url = (
        f"{os.getenv('SUPABASE_URL')}"
        f"/storage/v1/object/public/{BUCKET}/{nombre_file}"
    )
    return pdf_url


def eliminar_pdf(cedula):
    """Elimina el PDF de Supabase si ya no se necesita."""
    supabase = get_supabase()
    try:
        supabase.storage.from_(BUCKET).remove([f"pdfs/{cedula}.pdf"])
    except Exception:
        pass