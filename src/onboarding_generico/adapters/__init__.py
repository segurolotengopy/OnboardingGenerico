"""Adaptadores del hexágono.

- `inmemory`: implementación completa y funcional de todos los puertos. Es la
  que usan las pruebas y el desarrollo local; **no** requiere ninguna
  dependencia externa.
- `aws`: implementación de referencia. Importa `boto3` **dentro de las
  funciones**, nunca a nivel de módulo.
- `gcp`: alternativa. Importa `google-cloud-*` de la misma forma.
- `providers`: adaptadores de proveedores de capacidad (OSS y SaaS), cada uno
  con su nota de licencia.

Regla de arquitectura que las pruebas verifican: importar
`onboarding_generico.adapters` **no** puede fallar por falta de un SDK.
"""

from __future__ import annotations

__all__: list[str] = []
