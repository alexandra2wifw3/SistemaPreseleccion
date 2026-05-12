from supabase import create_client
import os

BUCKET = "postulantes"

def get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_KEY")
    )

def subir_pdf(cedula, pdf_bytes):
    """
    Sube el PDF a Supabase Storage.
    Retorna la URL pública del archivo.
    """
    supabase    = get_supabase()
    nombre_file = f"pdfs/{cedula}.pdf"

    # Si ya existe uno con esa cédula, lo reemplaza
    try:
        supabase.storage.from_(BUCKET).remove([nombre_file])
    except Exception:
        pass

    supabase.storage.from_(BUCKET).upload(
        nombre_file,
        pdf_bytes,
        {"content-type": "application/pdf", "upsert": "true"}
    )

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