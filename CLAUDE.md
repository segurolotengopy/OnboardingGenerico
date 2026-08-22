# Instrucciones para agentes de código

Este archivo orienta a asistentes de programación que trabajen sobre este repositorio. Los humanos deben leer [`CONTRIBUTING.md`](CONTRIBUTING.md) y [`docs/00-indice.md`](docs/00-indice.md).

## Qué es este proyecto

Middleware B2B serverless que orquesta flujos de onboarding e identidad digital componiendo capacidades de verificación de múltiples proveedores. Reside en AWS, en GCP o en ambas.

## Reglas que no se negocian

1. **El núcleo no importa SDK de nube.** `domain`, `ports`, `composer`, `application` y `crypto` funcionan con la biblioteca estándar. `ruff` bloquea `import boto3` fuera de `adapters/`. Si necesita una capacidad de infraestructura, defina o use un puerto.
2. **Los puertos exponen operaciones de dominio.** Nunca `PK`, `SK`, `begins_with`, `waitForTaskToken` ni ningún concepto de un proveedor concreto. Hay una prueba de arquitectura que verifica la superficie del puerto de repositorio.
3. **Los SDK se importan dentro de la función**, nunca a nivel de módulo, para que el paquete se importe sin los extras instalados. Si falta la dependencia, lance `MissingDependencyError` indicando qué extra instalar.
4. **`tenant_id` es Associated Data del cifrado.** Nunca lo elimine de una llamada de cifrado ni de descifrado "para simplificar". Es el control que convierte un error de alcance en un fallo de descifrado en vez de una fuga.
5. **Ningún dato binario ni respuesta completa de OCR viaja por el estado del orquestador.** Siempre `ObjectRef`. Cloud Workflows tope 512 KB acumulados por ejecución; Step Functions 256 KiB por payload.
6. **Ningún dato personal en registros, métricas ni trazas.** Use `observability.py`.
7. **Ningún secreto, credencial ni documento de identidad real en el repositorio**, ni siquiera en pruebas.

## Antes de cambiar una decisión estructural

Consulte [`docs/adr/`](docs/adr/). Si su cambio contradice un ADR aceptado, escriba primero el ADR que lo supersede; no lo implemente en silencio.

## Datos que no debe repetir

La especificación de origen contiene errores verificados. Antes de citar cualquier cifra de rendimiento, costo o cuota, consulte [`docs/20-fe-de-erratas-del-spec-original.md`](docs/20-fe-de-erratas-del-spec-original.md). En particular, nunca escriba que Lambda está limitado a 3 008 MB "para AVX-512", que Express Workflows ahorra un 72,5 %, ni que el `CachingCryptoMaterialsManager` es la solución al *cache stampede*.

## Verificación antes de entregar

```bash
make verificar        # ruff + mypy estricto + pytest
make smoke            # prueba de humo sin dependencias externas
make tf-fmt           # si tocó infraestructura
```

No entregue código que no haya ejecutado.

## Idioma

Identificadores, nombres de archivo, ramas y mensajes de commit en **inglés**. Comentarios, docstrings y documentación en **español latinoamericano sin voceo**.
