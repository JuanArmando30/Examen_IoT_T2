"""Límite de tasa en memoria (ventana deslizante).

La API corre en UN proceso de Uvicorn detrás de Caddy, así que basta un
contador en memoria. Si algún día se usan varios procesos, habría que
moverlo a Redis o a la base.
"""

import threading
import time
from collections import defaultdict, deque

from app.core.exceptions import DemasiadosIntentos


class LimitadorTasa:
    def __init__(self, maximo, ventana_s):
        self.maximo = maximo
        self.ventana_s = ventana_s
        self._eventos = defaultdict(deque)
        self._candado = threading.Lock()

    def registrar(self, clave):
        """Cuenta un intento; 429 si ya se alcanzó el máximo en la ventana."""
        ahora = time.monotonic()
        with self._candado:
            cola = self._eventos[clave]
            while cola and ahora - cola[0] > self.ventana_s:
                cola.popleft()
            if len(cola) >= self.maximo:
                espera = int(self.ventana_s - (ahora - cola[0])) + 1
                raise DemasiadosIntentos(f"Demasiados intentos. Vuelve a probar en {espera} s.")
            cola.append(ahora)
            if len(self._eventos) > 10000:                  # evita crecer sin límite
                for k in [k for k, v in self._eventos.items() if not v][:5000]:
                    del self._eventos[k]

    def reiniciar(self):
        with self._candado:
            self._eventos.clear()


def ip_cliente(request):
    """IP real del cliente. Detrás de Caddy (127.0.0.1) se usa X-Forwarded-For;
    si la petición no viene del proxy local, esa cabecera no se cree."""
    directa = request.client.host if request.client else "desconocida"
    if directa in ("127.0.0.1", "::1"):
        reenviada = request.headers.get("x-forwarded-for", "")
        if reenviada:
            return reenviada.split(",")[0].strip()
    return directa
