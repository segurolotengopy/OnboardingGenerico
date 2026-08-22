# Registros de decisión de arquitectura (ADR)

Este directorio contiene los **registros de decisión de arquitectura** de Onboarding Genérico. Cada ADR documenta una decisión estructural: el contexto en que se tomó, las opciones que se compararon, la decisión adoptada y las consecuencias que se aceptan a cambio.

Los ADR **no sustituyen** a la documentación de `docs/`. La documentación describe **cómo funciona** el sistema; los ADR explican **por qué es así y qué se descartó**. Cuando ambos parecen contradecirse, gana la documentación: significa que el ADR está obsoleto y hay que superarlo.

El formato es **Michael Nygard extendido**: a la plantilla original (Contexto / Decisión / Consecuencias) se le añaden tres secciones que este proyecto considera obligatorias —**Fuerzas en tensión**, **Opciones consideradas** con pros y contras honestos, y **Criterios de revisión**—, porque sin ellas un ADR se convierte en una justificación retrospectiva en lugar de un registro de decisión.

## Índice

| # | Título | Estado | Fecha | Ámbito |
|---|---|---|---|---|
| [0000](0000-plantilla.md) | Plantilla | — | 2026-08-21 | Proceso |
| [0001](0001-arquitectura-hexagonal-multinube.md) | Arquitectura hexagonal multinube con AWS de referencia | Aceptada | 2026-08-21 | Arquitectura |
| [0002](0002-terraform-como-iac-principal.md) | Terraform/OpenTofu como IaC principal | Aceptada | 2026-08-21 | Infraestructura |
| [0003](0003-python-312-como-runtime-principal.md) | Python 3.12 como runtime principal | Aceptada | 2026-08-21 | Plataforma |
| [0004](0004-orquestacion-hibrida-standard-express.md) | Orquestación híbrida Standard + Express anidados | Aceptada | 2026-08-21 | Orquestación |
| [0005](0005-aislamiento-multitenant-en-capas.md) | Aislamiento multi-tenant en capas con criptografía como control primario | Aceptada | 2026-08-21 | Seguridad |
| [0006](0006-hierarchical-keyring-en-lugar-de-cachingcryptomaterialsmanager.md) | Hierarchical keyring en lugar de `CachingCryptoMaterialsManager` | Aceptada | 2026-08-21 | Criptografía |
| [0007](0007-registro-de-capacidades-dirigido-por-especificacion.md) | Registro de capacidades dirigido por especificación | Aceptada | 2026-08-21 | Composición |
| [0008](0008-ocr-generico-mas-llm-en-lugar-de-analyzeid.md) | OCR genérico + LLM multimodal en lugar de `AnalyzeID` | Aceptada | 2026-08-21 | IA y extracción |
| [0009](0009-liveness-mediante-proveedor-certificado-unico.md) | Liveness mediante un único proveedor certificado | Aceptada | 2026-08-21 | Biometría |
| [0010](0010-revision-humana-construida-a-medida.md) | Revisión humana construida a medida en ambas nubes | Aceptada | 2026-08-21 | Operación |
| [0011](0011-punteros-a-objetos-en-lugar-de-payloads.md) | Punteros a objetos en lugar de payloads en el orquestador | Aceptada | 2026-08-21 | Orquestación |
| [0012](0012-politica-de-licencias-de-terceros.md) | Política de licencias de terceros | Aceptada | 2026-08-21 | Legal / Ingeniería |
| [0013](0013-residencia-de-datos-y-regionalizacion.md) | Residencia de datos y regionalización UE/LATAM | Aceptada | 2026-08-21 | Cumplimiento |
| [0014](0014-el-middleware-es-encargado-del-tratamiento.md) | El middleware es encargado del tratamiento | Aceptada | 2026-08-21 | Cumplimiento |
| [0015](0015-cadena-de-auditoria-con-hash-encadenado.md) | Cadena de auditoría con hash encadenado y almacenamiento WORM | Aceptada | 2026-08-21 | Auditoría |

## Reglas del proceso

### Cuándo se escribe un ADR

Se escribe un ADR cuando la decisión cumple **al menos una** de estas condiciones:

1. **Es costosa de revertir.** Cambiarla después implica migración de datos, reescritura de adaptadores o renegociación contractual. Ejemplos: el motor de orquestación, el formato del registro de auditoría, la longitud de un beacon de búsqueda (irreversible una vez escritos registros).
2. **Cruza límites de equipo o de capa.** Afecta simultáneamente al núcleo, a los adaptadores y a la infraestructura.
3. **Contradice una expectativa razonable.** Si un ingeniero nuevo se sorprendería al descubrirla, hay que explicarla. Los ADR [0006](0006-hierarchical-keyring-en-lugar-de-cachingcryptomaterialsmanager.md) y [0008](0008-ocr-generico-mas-llm-en-lugar-de-analyzeid.md) existen exactamente por esto.
4. **Tiene consecuencias regulatorias.** Cualquier decisión que un supervisor financiero o una autoridad de protección de datos podría cuestionar.

**No** se escribe un ADR para: elecciones de biblioteca reversibles en una tarde, convenciones de estilo (viven en `ruff`), ni nombres de recursos (viven en [CLAUDE.md](../../CLAUDE.md) y en los módulos de Terraform).

### Cómo se numera

- Numeración **secuencial de cuatro dígitos**, sin huecos y sin reutilización. `0000` está reservado para la plantilla.
- El número **se asigna al abrir el pull request**, no al empezar a escribir. Si dos ADR colisionan en el mismo número, renumera el que se fusione después.
- El nombre de archivo es `NNNN-titulo-en-kebab-case.md`, en **inglés no**: el título del archivo va en español sin tildes ni caracteres especiales, para evitar problemas de portabilidad de rutas.
- **Un número nunca se borra.** Un ADR retirado se marca como `Rechazada` o `Superada`, pero el archivo permanece: el valor histórico está en saber qué se consideró y por qué se abandonó.

### Estados admitidos

| Estado | Significado |
|---|---|
| `Propuesta` | En discusión. No se implementa todavía. |
| `Aceptada` | Vigente. El código y la infraestructura deben ser consistentes con ella. |
| `Rechazada` | Se consideró y se descartó. Se conserva para no volver a discutirla desde cero. |
| `Superada por ADR-NNNN` | Sustituida por una decisión posterior. |
| `Obsoleta` | El contexto desapareció (el servicio se retiró, la capacidad ya no se ofrece) sin que exista un sustituto directo. |

### Cómo se supersede un ADR

1. Se escribe un **ADR nuevo** con número nuevo. **Nunca** se edita el cuerpo de un ADR aceptado para cambiar la decisión: eso destruye el registro histórico.
2. El ADR nuevo cita al anterior en «Documentos relacionados» y explica en «Contexto» **qué hecho concreto cambió** —normalmente uno de los «Criterios de revisión» del ADR original se cumplió.
3. En el ADR antiguo se modifican **solo dos cosas**: el campo `Estado`, que pasa a `Superada por ADR-NNNN`, y una línea al principio con el enlace al sucesor. El resto del texto queda intacto, incluidas las afirmaciones que el tiempo demostró equivocadas.
4. Se actualiza la tabla de índice de este README.

### Regla de cifras

Toda cifra, cuota o artículo normativo citado en un ADR debe proceder de [`docs/referencias/`](../referencias/) y llevar **URL de la fuente primaria**. Si un dato no está verificado, se marca con `<!-- PENDIENTE DE VERIFICAR -->` y no se usa como base de una decisión. Las erratas del documento fuente original están catalogadas en [20 — Fe de erratas](../20-fe-de-erratas-del-spec-original.md); ningún ADR puede reintroducirlas.
