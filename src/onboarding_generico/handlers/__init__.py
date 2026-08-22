"""Puntos de entrada por nube.

Los manejadores son **envoltorios delgados**: traducen el formato del evento
al comando del caso de uso y el resultado a la respuesta HTTP. Toda la lógica
vive en `application` y `domain`, que es lo que permite que AWS y GCP
compartan comportamiento sin compartir código de infraestructura.
"""

from __future__ import annotations

__all__: list[str] = []
