from ..models import RegolaDocumento


def obbligatoria(regola, presente_nel_sysspy):
    """Se la scansione di un genere va caricata, secondo la regola decisa dall'Amministratore."""
    if regola == RegolaDocumento.SEMPRE:
        return True
    if regola == RegolaDocumento.SE_SYSSPY:
        return presente_nel_sysspy
    return False
