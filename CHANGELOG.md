# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Este proyecto sigue [Versionado Semántico](https://semver.org/lang/es/).

## [No publicado]

## [0.1.0] — 2026-08-21

Primera generación del repositorio: arquitectura, infraestructura y núcleo funcional.

### Añadido

- **Documentación** (`docs/`): 21 documentos de arquitectura, cumplimiento y operación, y 15 registros de decisión de arquitectura (ADR-0001 a ADR-0015).
- **Investigación de respaldo** (`docs/referencias/`): síntesis verificada de las arquitecturas de referencia de AWS, la matriz de paridad AWS→GCP con sus nueve brechas, y el marco normativo aplicable a Bolivia, Paraguay, México y la Unión Europea a agosto de 2026.
- **Núcleo del dominio** (`src/onboarding_generico/domain/`): implementación completa y probada de ICAO Doc 9303 (dígito de control 7-3-1, formatos TD1, TD2 y TD3, dígito compuesto), máquina de estados de la sesión, motor de decisión por umbrales del inquilino, y cadena de auditoría encadenada por hash.
- **Motor de composición** (`src/onboarding_generico/composer/`): parseo, validación y compilación de especificaciones de flujo a un plan de ejecución agnóstico, con emisores a Amazon States Language y a YAML de Cloud Workflows.
- **Capa criptográfica** (`src/onboarding_generico/crypto/`): cifrado de sobre por inquilino con `tenant_id` como Associated Data, política de cifrado por atributo y caché de material con carga atómica.
- **Puertos y adaptadores**: 17 puertos del núcleo; adaptadores en memoria completos y funcionales; esqueletos con firma y mapeo definidos para AWS, GCP y proveedores de visión artificial.
- **Infraestructura como código** (`infra/terraform/`): 20 módulos (10 para AWS, 10 para GCP) y tres entornos, con aislamiento ABAC real, cifrado por inquilino, orquestación híbrida y flujo de purga.
- **Contratos** (`api/`): especificación OpenAPI 3.1 y esquemas JSON del registro de capacidades, del conjunto canónico de datos de identidad y del resultado de verificación.
- **Integración continua** (`.github/workflows/`): calidad de código, pruebas, análisis de seguridad, validación de infraestructura y construcción de imágenes.
- **Pruebas**: 362 pruebas unitarias, de contrato y de arquitectura, más una prueba de humo sin dependencias externas.

### Corregido respecto de la especificación de origen

Ocho afirmaciones de la especificación previa se verificaron contra documentación oficial y resultaron falsas, obsoletas o mal atribuidas. Se documentan con evidencia en [`docs/20-fe-de-erratas-del-spec-original.md`](docs/20-fe-de-erratas-del-spec-original.md). Las de mayor impacto:

- El límite de memoria de AWS Lambda es de 128 MB a 10 240 MB, no 3 008 MB, y no existe ningún requisito de memoria vinculado a AVX-512.
- El ahorro del 72,5 % con Express Workflows no está respaldado por ninguna fuente; el costo debe calcularse por flujo.
- La reducción del 77 % del costo de KMS **no** se obtuvo con `CachingCryptoMaterialsManager`: la fuente lo describe como la causa del problema de *cache stampede*.
