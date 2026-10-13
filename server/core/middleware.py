from . import contesto


class AzzeraContestoMiddleware:
    """Ogni richiesta parte e finisce senza cliente: il thread non se lo porta dietro."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        contesto.azzera()
        try:
            return self.get_response(request)
        finally:
            contesto.azzera()
