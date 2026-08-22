# ADR-0016 — Python 3.14 como runtime principal, superando a ADR-0003

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-22 |
| Decisores | Arquitectura de plataforma |
| Supersede a | [ADR-0003](0003-python-312-como-runtime-principal.md) |
| Documentos relacionados | [ADR-0001](0001-arquitectura-hexagonal-multinube.md) · [ADR-0008](0008-ocr-generico-mas-llm-en-lugar-de-analyzeid.md) · [16 — Guía de despliegue AWS](../16-guia-de-despliegue-aws.md) · [18 — Desarrollo local](../18-desarrollo-local.md) |

## Contexto

[ADR-0003](0003-python-312-como-runtime-principal.md) decidió dos cosas a la vez: que el lenguaje del núcleo y de los adaptadores sería **Python**, y que la versión sería **3.12**. La primera decisión sigue siendo válida y este ADR la mantiene íntegra junto con su razonamiento: la inferencia ONNX en proceso que `FaceMatchPort` necesita en GCP, la madurez de los *bindings* nativos de visión artificial y la existencia de Tink en Python siguen siendo argumentos vigentes.

Lo que se revisa aquí es solo la **versión**, por tres motivos que no existían cuando se escribió ADR-0003.

**Primero, el horizonte de soporte se acorta.** El catálogo de runtimes gestionados de AWS Lambda fija el fin de soporte de `python3.12` el **31 de octubre de 2028**, mientras que `python3.14` llega hasta el **30 de junio de 2029**. Un middleware de identidad regulado no debería estar a dos años de la caducidad de su runtime sin un plan escrito.

**Segundo, el propio ADR-0003 fijó el disparador.** Entre sus criterios de revisión está: *«Si el modo sin GIL de CPython alcanza soporte productivo en ambos runtimes gestionados y las dependencias nativas lo soportan, procede reevaluar el modelo de concurrencia»*. Python 3.14 es la primera versión donde el modo sin GIL deja de ser experimental y pasa a estar oficialmente soportado. La condición se cumple a medias —se explica más abajo— pero basta para que el ADR se revise por su propia regla en vez de por inercia.

**Tercero, el ecosistema ya está listo.** El obstáculo que ADR-0003 consideraba decisivo era la madurez de las dependencias nativas. Se verificó contra PyPI, no se supuso:

| Paquete | Versión | Soporte 3.14 |
|---|---|---|
| `onnxruntime` | 1.29.0 | 7 ruedas `cp314` |
| `numpy` | 2.5.2 | 21 ruedas `cp314` |
| `Pillow` | 12.3.0 | 21 ruedas `cp314` |
| `pydantic-core` | 2.48.0 | 31 ruedas `cp314` |
| `tink` | 1.16.1 | 4 ruedas `cp314` |
| `opencv-python-headless` | 5.0.0.93 | `cp37-abi3`, ABI estable: válida en 3.14 |
| `fastapi`, `uvicorn`, `boto3`, `google-cloud-*` | — | Puras, independientes de la versión |

Ninguna dependencia bloquea la subida.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Horizonte de soporte del runtime gestionado | Determina cuándo hay que volver a hacer este trabajo |
| Coste de cada migración de versión | Cada salto consume capacidad que no va a producto |
| Disponibilidad del runtime en **ambas** nubes | Un runtime que solo existe en una rompe la paridad de ADR-0001 |
| Madurez de las dependencias nativas | Un `onnxruntime` sin ruedas deja a `FaceMatchPort` sin adaptador en GCP |
| Estabilidad frente a novedad | Una versión recién publicada acumula menos horas de vuelo en producción |
| Compatibilidad hacia atrás del código | `requires-python` bajo permite que distribuciones estables ejecuten las pruebas |

## Opciones consideradas

### Opción A — Permanecer en 3.12

**A favor**
- Coste cero hoy. El runtime está probado y en producción en el catálogo de Lambda desde hace años.
- Máxima cantidad de horas de vuelo acumuladas del ecosistema sobre esa versión.

**En contra**
- El fin de soporte es el 31 de octubre de 2028, y Lambda bloquea la *creación* de funciones 30 días después y la *actualización* a partir del 10 de enero de 2029.
- Aplaza el trabajo sin eliminarlo, y lo concentra en un momento futuro que no elegimos nosotros.
- Deja sin atender un criterio de revisión que el propio ADR-0003 se impuso.

### Opción B — Subir a 3.13

**A favor**
- Salto más corto y por tanto con menos superficie de cambios de comportamiento.
- Lambda lo ofrece con el mismo fin de soporte que 3.14: **30 de junio de 2029**.

**En contra**
- **No aporta ningún horizonte adicional frente a 3.14**: ambas caducan el mismo día. Se paga el coste de una migración para quedarse una versión por detrás.
- Obliga a repetir la migración antes que la Opción C para acceder a las mismas características del lenguaje.

### Opción C — Subir a 3.14

**A favor**
- Fin de soporte el 30 de junio de 2029, ocho meses más que 3.12 y el mismo que 3.13 pero una versión más adelante.
- Disponible como runtime gestionado en Lambda sobre Amazon Linux 2023 y como imagen base oficial, lo que cubre los dos formatos de empaquetado del proyecto.
- Todas las dependencias nativas ya publican ruedas, según la verificación de arriba.
- Es la primera versión con el modo sin GIL oficialmente soportado, lo que desbloquea la reevaluación de concurrencia que ADR-0003 dejó pendiente.

**En contra**
- Menos horas de vuelo acumuladas que 3.12 en cargas de producción.
- Obliga a mantener temporalmente tres versiones en la matriz de pruebas.

### Opción D — Subir a 3.15

**A favor**
- El horizonte de soporte más largo posible.

**En contra**
- **Descartada sin discusión.** La documentación de AWS la marca como *public preview*, explícitamente fuera del SLA y del soporte técnico, y advierte que no debe usarse en cargas de producción. Un middleware de identidad regulado no es el sitio para una vista previa.

## Decisión

**Se adopta Python 3.14 como runtime principal** del núcleo, de los adaptadores y de ambos formatos de empaquetado, superando a ADR-0003 en lo relativo a la versión y manteniendo intacta su decisión sobre el lenguaje.

El código sigue siendo **compatible con 3.11 en adelante**: `requires-python` permanece en `>=3.11`, `ruff` mantiene `target-version = "py311"` y `mypy` mantiene `python_version = "3.11"`. Esa compatibilidad no es simbólica —la matriz de integración continua ejecuta las pruebas en 3.11, 3.12 y 3.14— y existe para que una distribución estable pueda ejecutar la batería sin construir un intérprete.

Este ADR **no cambia el modelo de concurrencia**. Los runtimes gestionados de Lambda y las imágenes base oficiales siguen distribuyendo la construcción con GIL; el modo sin GIL exige una construcción propia. Lo que cambia es que la versión del lenguaje deja de ser el obstáculo, de modo que la reevaluación que ADR-0003 previó puede abordarse cuando haya motivo, y no antes.

## Consecuencias

### Positivas

- El horizonte de soporte del runtime pasa de octubre de 2028 a junio de 2029, y la próxima migración obligatoria se decide con calendario propio.
- La matriz de pruebas cubre por primera vez tres versiones, lo que convierte la compatibilidad declarada en `requires-python` en algo comprobado y no en una afirmación.
- El criterio de revisión sobre el modo sin GIL queda atendido de forma explícita en lugar de caducar en silencio.
- Las imágenes de contenedor y el runtime gestionado de Lambda quedan alineados en la misma versión, que antes solo coincidía por costumbre.

### Negativas

- Se adopta una versión con menos horas de vuelo en producción que la que se abandona. El riesgo se acota con la matriz de tres versiones: un cambio de comportamiento que rompa en 3.14 y no en 3.12 aparece en integración continua antes de llegar a un despliegue.
- La matriz de tres versiones alarga cada ejecución de integración continua y consumirá minutos de ejecución adicionales.
- Quien desarrolle en local con 3.12 no reproducirá exactamente el runtime de producción. El código sigue funcionando, pero un fallo específico de 3.14 solo se verá en integración continua.
- `.pre-commit-config.yaml` mantiene `python3.12` como intérprete de los ganchos a propósito, para no exigir 3.14 instalado a quien solo quiera ejecutar el lint. Es una inconsistencia deliberada entre el runtime y las herramientas locales.

### Neutras

- El valor por omisión de `var.python_runtime` pasa a `python3.14`. Un entorno que necesite otra versión la sigue pasando de forma explícita, sin tocar el módulo.
- La cobertura pasa a publicarse desde el trabajo de 3.14, que es el runtime principal, y no desde el de 3.12.
- Se mantienen los clasificadores de 3.11 y 3.12 en el paquete, porque siguen siendo versiones soportadas por el código.

## Criterios de revisión

- **Si `python3.15` sale de vista previa y alcanza disponibilidad general** en Lambda y en Cloud Run, procede planificar la siguiente subida sin esperar a 2029.
- **Si una dependencia nativa retira las ruedas `cp314`** o deja de publicarlas para una versión posterior, el ecosistema vuelve a ser el factor decisivo y este ADR debe releerse antes de subir de nuevo.
- **Si los runtimes gestionados empiezan a distribuir la construcción sin GIL**, se cumple por completo el criterio que ADR-0003 dejó abierto y procede reevaluar el modelo de concurrencia y el dimensionado, que este ADR deja sin tocar.
- **Si la matriz de tres versiones se vuelve un coste desproporcionado**, procede reducirla a la mínima soportada y la principal, subiendo `requires-python` de forma explícita en lugar de dejar de probar.
- **Si aparece un fallo de producción atribuible a 3.14** que no se reproduzca en 3.12, procede volver atrás: el cambio es reversible mientras `requires-python` siga en `>=3.11`.

## Referencias

- [Lambda runtimes — catálogo de runtimes soportados y fechas de fin de soporte](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)
- [ADR-0003 — Python 3.12 como runtime principal](0003-python-312-como-runtime-principal.md), superado por este documento
- [ADR-0001 — Arquitectura hexagonal multinube](0001-arquitectura-hexagonal-multinube.md)
- [18 — Desarrollo local](../18-desarrollo-local.md)
