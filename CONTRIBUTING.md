# Guía de contribución

Gracias por contribuir. Este documento describe el flujo de trabajo, las reglas de calidad y los controles que un cambio debe superar antes de integrarse.

## Antes de escribir código

1. Lea [`docs/00-indice.md`](docs/00-indice.md) y ubique el documento que cubre el área que va a tocar.
2. Revise los [ADR](docs/adr/) relacionados. Si su cambio contradice una decisión aceptada, **no lo implemente todavía**: abra primero un ADR que la supersede.
3. Si va a integrar un componente de terceros, pase antes por [ADR-0012 — Política de licencias de terceros](docs/adr/0012-politica-de-licencias-de-terceros.md). Es un control bloqueante, no una recomendación.

## Flujo de trabajo

```bash
git checkout -b feat/descripcion-corta      # feat | fix | docs | infra | chore | refactor | test
make install
# ... cambios ...
make verificar                              # lint + tipos + pruebas
git commit                                  # ver convención abajo
git push -u origin feat/descripcion-corta
```

Las ramas se integran mediante *pull request* con al menos una aprobación. `main` está protegida.

### Convención de commits

Se usa [Conventional Commits](https://www.conventionalcommits.org/) **en inglés**, aunque la documentación del proyecto esté en español:

```
feat(composer): support fallback provider resolution per step
fix(mrz): accept '<' as personal number check digit in TD3
docs(adr): supersede ADR-0009 with SaaS liveness decision
infra(aws): add object lock to evidence bucket
```

Ámbitos habituales: `domain`, `ports`, `composer`, `application`, `crypto`, `adapters`, `handlers`, `infra`, `docs`, `adr`, `ci`.

## Reglas de código

| Regla | Motivo |
|---|---|
| Identificadores y nombres de archivo en **inglés**; comentarios, docstrings y documentación en **español latinoamericano sin voceo** | Convención del proyecto |
| El núcleo (`domain`, `ports`, `composer`, `application`, `crypto`) **no importa ningún SDK de nube** | Es lo que hace posible el adaptador de la segunda nube. `ruff` lo bloquea con `banned-api` |
| Los SDK de nube se importan **dentro de la función**, nunca a nivel de módulo | Permite importar el paquete sin instalar los extras |
| Los puertos exponen **operaciones de dominio**, nunca `PK`, `SK` ni `begins_with` | Un puerto acoplado a DynamoDB hace inviable Firestore. Hay una prueba de arquitectura que lo verifica |
| Anotaciones de tipo completas; `mypy --strict` sobre el núcleo | El núcleo es la superficie que más cuesta corregir después |
| Ningún dato personal en registros, métricas ni atributos de traza | Use `observability.py`, que redacta por lista de claves |
| Ningún secreto, credencial ni dato de identidad real en el repositorio | `gitleaks` y `detect-private-key` lo bloquean en el *hook* |
| Los objetos de valor son `@dataclass(frozen=True, slots=True)` | Inmutabilidad por defecto en el dominio |

## Añadir un adaptador de proveedor

Es el cambio más frecuente. El procedimiento completo está en [`docs/18-desarrollo-local.md`](docs/18-desarrollo-local.md). En resumen:

1. Identifique el puerto en `src/onboarding_generico/ports/`. Si no existe, **primero** discuta el puerto: añadir un puerto es una decisión de arquitectura.
2. Implemente el adaptador en `src/onboarding_generico/adapters/providers/`, con la nota de licencia del componente y de los pesos del modelo en el docstring del módulo.
3. Registre la capacidad y el proveedor en el Registro de Capacidades (ver [`docs/04-motor-de-composicion.md`](docs/04-motor-de-composicion.md)).
4. Añada la prueba de conformidad en `tests/contract/test_port_conformance.py`.
5. Documente el proveedor en [`docs/15-catalogo-de-proveedores-y-licencias.md`](docs/15-catalogo-de-proveedores-y-licencias.md), incluyendo licencia verificada y veredicto de aptitud comercial.

## Qué debe traer una *pull request*

- Descripción de qué cambia y por qué; enlace al issue o al ADR.
- Pruebas nuevas o modificadas que fallarían sin el cambio.
- Documentación actualizada si el cambio altera un contrato, un despliegue o una decisión.
- Si toca infraestructura: la salida de `terraform plan` del entorno `dev`.
- Si toca el modelo de datos o la criptografía: análisis explícito del impacto en el aislamiento por inquilino.

## Datos de prueba

Está **prohibido** versionar documentos de identidad, imágenes faciales o datos personales reales, incluso propios. Use los generadores sintéticos de `tests/fixtures/` y los ejemplos canónicos de ICAO Doc 9303, que son ficticios por diseño.
