# ADR-0012 — Política de licencias de terceros: prohibición de AGPL y de código sin licencia, revisión legal para Elastic License 2.0, y evaluación separada de la licencia de los pesos

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [15 — Catálogo de proveedores y licencias](../15-catalogo-de-proveedores-y-licencias.md) · [ADR-0009](0009-liveness-mediante-proveedor-certificado-unico.md) · [ADR-0008](0008-ocr-generico-mas-llm-en-lugar-de-analyzeid.md) · [14 — Modelo de amenazas](../14-modelo-de-amenazas.md) |

## Contexto

El middleware es un **producto propietario expuesto por red** que se ofrece como servicio a terceros. Esas dos características determinan qué licencias son compatibles, y lo hacen de forma más estricta que en una aplicación interna o en un binario distribuido.

La revisión del ecosistema de eKYC de código abierto que el spec original proponía reutilizar arrojó resultados en su mayoría negativos:

| Componente | Licencia verificada | Efecto |
|---|---|---|
| `fastmrz` | **AGPL-3.0** | Copyleft de red: incompatible con producto propietario expuesto por red |
| `Laligence-Dev/ekyc-system` | **Sin licencia** | Todos los derechos reservados: no hay concesión de uso |
| `YegorCherov/document-scanner` | **Sin licencia** | Idem |
| `OmniMRZ` | **Contradicción**: `LICENSE` dice Apache-2.0, el distintivo del README dice AGPL-3.0 | Ambigüedad no resoluble por ingeniería |
| Backend de **Ballerine** | Por defecto **Elastic License 2.0** | Prohíbe ofrecerlo como servicio gestionado a terceros |
| `@openeudi/*` | **Apache-2.0** | Utilizable |
| `minivision-ai/Silent-Face-Anti-Spoofing` | **Apache-2.0** | Utilizable, pero modelo de 2020 |
| `fbieberly/document_warp`, `joellijo32/Document-Scanner-using-OpenCV` | **MIT** | Utilizables como código de referencia |
| `team-idswyft/idswyft-community` | **MIT** | Utilizable |

Y hay un problema de otra naturaleza, que el análisis de composición **no detecta**: varios **pesos de modelos** de reconocimiento facial y análisis forense de imagen —InsightFace `buffalo_l`, TruFor— arrastran restricciones de uso no comercial **independientes de la licencia del código**. Los pesos no son un paquete, no aparecen en el manifiesto de dependencias y no tienen metadatos de licencia normalizados. El código es utilizable; los pesos, no. Y sin pesos, el código no hace nada.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Producto propietario ofrecido por red | Activa el copyleft de red por definición, sin distribuir binarios |
| Velocidad de desarrollo | El ecosistema abierto ahorra trabajo real, y prohibirlo cuesta |
| Riesgo legal difícil de revertir | Una dependencia contaminante descubierta tarde obliga a reescribir |
| Herramientas de análisis de composición | Detectan licencias de paquetes, no de pesos de modelos |
| Ambigüedad documental de algunos proyectos | Ingeniería no debe resolver contradicciones de licencia |
| Licencias que cambian entre versiones | Una actualización rutinaria puede introducir una licencia prohibida |

## Opciones consideradas

### Opción A — Evaluación caso por caso, sin lista de prohibición

**A favor**
- Máxima flexibilidad: no se descarta de antemano un componente usable en condiciones concretas.
- Evita rechazar por reflejo licencias inusuales pero aceptables en el uso previsto.
- Coste inicial nulo: sin política que definir ni controles que construir.

**En contra**
- **No es automatizable**: depende de que quien incorpora la dependencia recuerde revisar, y las transitivas se cuelan sin que nadie las mire.
- La consecuencia de un error es asimétrica y tardía: una dependencia AGPL descubierta tras firmar contratos obliga a reescribir el componente.
- Traslada a ingeniería una decisión legal, con el sesgo previsible de quien quiere entregar la funcionalidad.
- No cubre en absoluto el problema de los pesos de modelos.

### Opción B — Solo MIT, Apache-2.0 y BSD, sin excepciones

**A favor**
- Trivial de automatizar y de explicar; sin zona gris que discutir.
- Riesgo legal mínimo y auditable en un cuestionario de cliente con una sola frase.
- Sin coste de proceso: sin revisiones legales ni excepciones que mantener.

**En contra**
- **Demasiado restrictiva en la práctica**: excluye LGPL y MPL-2.0, habitualmente aceptables como biblioteca sin modificar, y que aparecen en transitivas de bibliotecas normales.
- Sin mecanismo de excepción, un bloqueo legítimo no tiene salida y el equipo acaba saltándose la política o duplicando funcionalidad.
- Ignora las **obligaciones** de las licencias permitidas: conservar el `NOTICE` de Apache-2.0, declarar modificaciones, conservar el aviso de MIT.
- Tampoco cubre los pesos de modelos.

### Opción C — Tres categorías, puerta automática en CI y evaluación separada de los pesos

**A favor**
- La automatización cubre lo automatizable —paquetes y transitivas— y la revisión legal cubre la zona gris con la autoridad adecuada.
- **Trata la licencia de los pesos como un problema distinto**, con un procedimiento propio que el análisis de composición no puede realizar.
- Bloquear la construcción hace el control inevitable, igual que con una vulnerabilidad crítica.
- El inventario archivado con cada artefacto permite responder «¿usamos X?» en minutos.
- La detección de cambio de licencia entre versiones cierra la vía por la que una actualización introduce una licencia prohibida.

**En contra**
- Requiere construir y mantener los controles: puerta en CI, inventario, registro de excepciones, registro de modelos.
- Introduce fricción: una revisión legal puede tardar días y bloquear una entrega.
- El registro de modelos es trabajo manual que ninguna herramienta automatiza hoy, y depende de que las tarjetas de modelo del origen sean honestas.
- Falsos positivos sobre paquetes con metadatos mal declarados, que hay que triar.

## Decisión

**Se adopta la opción C**, con tres categorías y tres reglas duras.

**Categorías:**

- ✅ **Permitidas**: MIT, Apache-2.0, BSD de 2 y 3 cláusulas, ISC, Python Software Foundation, Zlib, Unlicense, CC0.
- ⚠️ **Requieren revisión legal**: LGPL 2.1 y 3.0, MPL-2.0, EPL, CDDL, **Elastic License 2.0**, licencias duales con opción comercial y licencias personalizadas. **La decisión no la toma ingeniería.**
- 🔴 **Prohibidas**: **AGPL en todas sus versiones**, GPL 2 y 3 para código enlazado, SSPL, BSL, Commons Clause, cualquier licencia «no comercial», **ausencia de licencia**, y **licencias contradictorias sin aclaración**.

**Regla 1 — La AGPL está prohibida sin excepción.** Su sección 13 obliga a ofrecer el código fuente a quienes interactúan con el software **a través de la red**. Un middleware expuesto por red la activa por definición. `fastmrz` queda descartado por eso, y `OmniMRZ` por su contradicción documental: mientras el autor no aclare qué licencia rige, el componente es inutilizable.

**Regla 2 — El código sin licencia está prohibido.** «Sin licencia» no es «dominio público»: es **todos los derechos reservados**. `Laligence-Dev/ekyc-system` y `YegorCherov/document-scanner` quedan descartados; pueden leerse como referencia intelectual, no copiarse.

**Regla 3 — La licencia de los pesos del modelo se evalúa por separado de la del código.** Es la regla más importante de este ADR porque ninguna herramienta la aplica automáticamente. Antes de incorporar un modelo hay que: localizar la licencia **de los pesos**, no la del repositorio; verificar la licencia del **conjunto de datos de entrenamiento**, cuyas restricciones se propagan; verificar restricciones de uso —investigación, no comercial, campo de uso— y de **redistribución**, incluida la de hornear los pesos en una imagen de contenedor; documentarlo en el registro de modelos; y escalar a revisión legal ante cualquier duda. **Un modelo con licencia de pesos desconocida no llega a producción.**

**La Elastic License 2.0 va a revisión legal, no a prohibición automática.** Su restricción central —prohibir ofrecer el software como servicio gestionado a terceros— choca frontalmente con el modelo de negocio, de modo que el resultado esperado es negativo para el backend de Ballerine. Pero admite usos que no la activan, y esa distinción es jurídica, no técnica.

**Aplicación técnica**: puerta de licencia en CI que **bloquea la construcción**; inventario de componentes archivado con cada artefacto; registro de excepciones con componente, versión, licencia, aprobador, condiciones y fecha de revisión; revisión obligatoria ante cambio de licencia entre versiones; y fijación de versión con hash. **Obligaciones de las permitidas**: archivo de avisos de terceros generado desde el inventario, concatenación de los `NOTICE` de Apache-2.0, declaración de modificaciones, y prohibición de usar el nombre de un componente para promocionar el producto.

## Consecuencias

### Positivas

- Riesgo legal acotado y demostrable: política escrita más inventario por artefacto.
- El bloqueo en CI evita que una dependencia contaminante entre por descuido o por vía transitiva.
- El registro de modelos cubre un riesgo que el análisis de composición no ve y que en biometría es el más probable.
- El inventario permite responder en minutos a «¿está afectado el producto por X?».

### Negativas

- Se renuncia a componentes útiles: `fastmrz` habría ahorrado trabajo de MRZ y el backend de Ballerine cubre funcionalidad real.
- Fricción de proceso: una revisión legal puede bloquear una entrega varios días.
- El registro de modelos es trabajo manual recurrente, dependiente de la honestidad de la documentación del origen.
- Falsos positivos que hay que triar sin desactivar la puerta.

### Neutras

- Implementar la MRZ de forma propia conforme a ICAO Doc 9303 resulta una ventaja colateral: `MrzPort` es el único puerto con **riesgo de portaje nulo**, porque el mismo código corre en las tres implementaciones.
- Los componentes sin licencia pueden leerse como referencia intelectual sin copiar código; la frontera está documentada.
- Esta política refuerza de forma independiente [ADR-0009](0009-liveness-mediante-proveedor-certificado-unico.md): un contrato comercial concede derechos explícitos, mientras que unos pesos descargados trasladan al integrador la carga de verificar una cadena de licencias a menudo indocumentada.

## Criterios de revisión

- **Si el autor de `OmniMRZ` resuelve la contradicción** a favor de Apache-2.0, el componente pasa a evaluable.
- **Si un componente hoy permitido cambia de licencia** —el precedente de migraciones a BSL o SSPL es abundante—, la actualización queda bloqueada hasta revisión y hay que planificar la sustitución.
- **Si el modelo de negocio cambia** y el producto deja de ofrecerse por red, la prohibición de AGPL debería reevaluarse: su fundamento es la sección 13, no un rechazo genérico al copyleft.
- **Si aparecen herramientas fiables de análisis de licencias de pesos**, parte del procedimiento manual puede automatizarse.
- **Si una revisión legal bloquea de forma recurrente la misma categoría**, conviene moverla a prohibida para ahorrar el ciclo.

## Referencias

- [GNU Affero General Public License v3.0 — sección 13](https://www.gnu.org/licenses/agpl-3.0.html)
- [Elastic License 2.0](https://www.elastic.co/licensing/elastic-license)
- [Apache License 2.0 — secciones 4(b) y 6](https://www.apache.org/licenses/LICENSE-2.0)
- [Fe de erratas del spec original](../20-fe-de-erratas-del-spec-original.md)
- [15 — Catálogo de proveedores y licencias §4 y §5](../15-catalogo-de-proveedores-y-licencias.md)
- [cumplimiento-normativo-y-estandares §A.1 — ICAO Doc 9303](../referencias/cumplimiento-normativo-y-estandares.md)
