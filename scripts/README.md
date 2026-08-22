# Utilidades

| Script | Qué hace | Cuándo se usa |
|---|---|---|
| `check_docs_links.py` | Verifica que ningún enlace relativo de la documentación esté roto | Integración continua, y antes de una entrega documental |
| `validate_flow_spec.py` | Valida una especificación de flujo contra su esquema JSON y contra el Registro de Capacidades | Antes de publicar una versión nueva de un flujo |
| `bootstrap_tenant.py` | Genera el plan de alta de un inquilino nuevo | Al incorporar un cliente B2B |
| `verify_mrz.py` | Valida una MRZ y muestra el detalle de cada dígito de control | Diagnóstico de rechazos documentales |

Todos funcionan con la biblioteca estándar de Python; ninguno requiere credenciales de nube.
