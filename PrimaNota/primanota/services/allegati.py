"""
Allegati più leggeri prima di salvarli in Baserow. Le foto le rimpicciolisce già il browser del negozio
(upload.html); qui si alleggeriscono i PDF delle scansioni: immagini ricompresse a 150 dpi e file ripulito.
Se qualcosa non va, o il risultato non è più piccolo, si tiene l'originale.
"""

import logging

from django.core.files.uploadedfile import SimpleUploadedFile

log = logging.getLogger(__name__)

SOGLIA = 300 * 1024   # sotto i 300 KB non vale la pena


def ottimizza(documento):
    """Il documento caricato, alleggerito se è un PDF pesante; altrimenti quello originale."""
    nome = getattr(documento, "name", "") or ""
    if not nome.lower().endswith(".pdf") or (documento.size or 0) < SOGLIA:
        return documento
    try:
        import pymupdf
        documento.seek(0)
        originale = documento.read()
        documento.seek(0)
        doc = pymupdf.open(stream=originale, filetype="pdf")
        if hasattr(doc, "rewrite_images"):   # PyMuPDF 1.24.3 e successivi
            doc.rewrite_images(dpi_threshold=200, dpi_target=150, quality=70)
        leggero = doc.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True)
    except Exception:
        log.exception("PDF %s non ottimizzato", nome)
        documento.seek(0)
        return documento
    if len(leggero) > len(originale) * 0.9:
        return documento
    log.info("PDF %s: %d KB -> %d KB", nome, len(originale) // 1024, len(leggero) // 1024)
    return SimpleUploadedFile(nome, leggero, content_type="application/pdf")
