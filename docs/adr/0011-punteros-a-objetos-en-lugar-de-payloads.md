# ADR-0011 — Punteros a almacenamiento de objetos en lugar de payloads en el estado del orquestador

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [07 — Orquestación](../07-orquestacion.md) · [ADR-0004](0004-orquestacion-hibrida-standard-express.md) · [ADR-0005](0005-aislamiento-multitenant-en-capas.md) · [ADR-0015](0015-cadena-de-auditoria-con-hash-encadenado.md) · [02 — Arquitectura](../02-arquitectura.md) |

## Contexto

Una sesión de onboarding manipula artefactos voluminosos: imágenes del anverso y el reverso del documento, el *selfie* o los fotogramas de la sesión de vida, y las respuestas completas de OCR, que para una página a resolución razonable contienen cientos de bloques con texto, geometría y confianza.

La ruta ingenua —pasar esos artefactos entre pasos dentro del estado del orquestador— choca con los límites de plataforma:

| Límite | Valor |
|---|---|
| Step Functions — payload de entrada/salida | **256 KiB** (UTF-8), Standard y Express |
| Step Functions Standard — tamaño de historial | **25.000 eventos** por ejecución |
| Cloud Workflows — datos acumulados por ejecución | **512 KB**, el más restrictivo de todos |
| Lambda — payload de invocación síncrona | **6 MB** (petición y respuesta) |
| Lambda — payload de invocación asíncrona | **1 MB** |

El de Cloud Workflows decide: **512 KB acumulados por toda la ejecución**, no por paso. Una sola imagen codificada en base64 lo agota, y una respuesta de OCR de una página también puede hacerlo. La investigación de paridad es explícita: pasar punteros a GCS, nunca payloads.

Hay una razón que sobrevive a cualquier ampliación futura de esos límites. El historial de Step Functions Standard se retiene **90 días** y es legible por cualquier principal con permiso sobre la ejecución. Meter una respuesta de OCR con nombre, número de documento y fecha de nacimiento en el estado del orquestador significa **replicar datos de categoría especial en un almacén que no está cifrado por tenant, que no aplica la política de retención del expediente y que no participa del control criptográfico de aislamiento** de [ADR-0005](0005-aislamiento-multitenant-en-capas.md). El límite de tamaño es la restricción visible; la de protección de datos es la importante.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| 512 KB acumulados en Cloud Workflows | Descarta cualquier payload voluminoso en el estado |
| 256 KiB por payload en Step Functions | Descarta binarios y respuestas OCR completas |
| El estado del orquestador no está cifrado por tenant | PII en el estado elude el control primario de aislamiento |
| Retención de 90 días del historial | Crea una copia de PII con política de borrado distinta a la del expediente |
| Un salto de red por artefacto | Coste de latencia frente a pasar el dato en el estado |
| Depuración de una ejecución | Un estado con punteros es menos legible que uno con datos |

## Opciones consideradas

### Opción A — Payloads en línea, con truncado cuando no quepan

**A favor**
- Simplicidad máxima: cada paso recibe lo que necesita sin resolver referencias.
- Depuración cómoda: la consola muestra la entrada y la salida reales de cada paso.
- Sin latencia añadida ni ciclo de vida de artefactos intermedios que gestionar.

**En contra**
- **Imposible con binarios**: una imagen no cabe en 256 KiB codificada, y menos en los 512 KB acumulados de Cloud Workflows.
- El truncado es peor que el fallo: produce extracciones incompletas de forma silenciosa, con resultados que parecen válidos.
- **Replica PII de categoría especial** en el historial, fuera del cifrado por tenant y con retención propia.
- El estado grande infla el historial y acerca el límite de 25.000 eventos.

### Opción B — Almacén intermedio en la base de datos de sesión

Guardar los artefactos como atributos del agregado de sesión y pasar solo el identificador.

**A favor**
- Un único almacén para el estado del caso: menos piezas móviles.
- Los datos quedan bajo el cifrado por tenant y bajo la política de retención del expediente.
- Consistencia con el resto de la persistencia y con las operaciones de dominio del repositorio.

**En contra**
- **Los binarios no caben ni son adecuados**: DynamoDB limita el ítem a 400 KB y Firestore a 1 MiB por documento.
- Almacenar blobs grandes en una base orientada a documentos degrada rendimiento y encarece cada lectura del agregado.
- No permite entrega directa desde el cliente: la imagen tendría que atravesar la API, que pasa a ser cuello de banda.
- No aprovecha las políticas de ciclo de vida ni el almacenamiento inmutable, que son los mecanismos que el resto del diseño usa para retención y evidencia.

### Opción C — Punteros con URLs prefirmadas

Todo artefacto vive en almacenamiento de objetos (`s3://` o `gs://`). Por el estado viaja únicamente una **referencia**: URI, hash del contenido, tipo, tamaño, versión de esquema y contexto de cifrado. La carga y la descarga por clientes y proveedores usan **URLs prefirmadas** de vida corta.

**A favor**
- **Respeta los tres límites** —256 KiB, 512 KB acumulados y el tamaño de ítem— con margen amplio e independientemente del contenido.
- La PII voluminosa nunca entra en el historial: no hay copia fuera del cifrado por tenant ni fuera de la retención del expediente.
- La imagen se sube directamente desde el cliente, sin atravesar la API del middleware.
- Las políticas de ciclo de vida aplican borrado automático a los artefactos intermedios, que es lo que exige la minimización del art. 25 del GDPR.
- El hash del contenido en la referencia sirve de base para la evidencia y el encadenamiento de auditoría ([ADR-0015](0015-cadena-de-auditoria-con-hash-encadenado.md)).
- `ObjectStoragePort` se porta con riesgo bajo: S3 y GCS tienen semántica equivalente para lo que aquí se usa.

**En contra**
- Cada paso que necesita el contenido paga una lectura adicional: más latencia y más llamadas.
- Ciclo de vida propio que gestionar, con riesgo de referencias colgantes.
- Depurar es menos directo: el estado muestra referencias, y ver el contenido exige resolverlas con permisos.
- La URL prefirmada es una credencial portadora: si se filtra, da acceso al objeto hasta que expira.

## Decisión

**Se adopta la opción C: por el estado del orquestador viajan exclusivamente punteros. Ningún dato binario y ninguna respuesta OCR completa entran en el estado.** La regla se formula en positivo para que sea verificable: **el payload entre pasos contiene identificadores, referencias, veredictos y puntuaciones; nunca contenido**.

El argumento es doble. De viabilidad: con **512 KB acumulados por ejecución en Cloud Workflows**, cualquier otra opción hace inviable el adaptador de GCP, y el límite es acumulado, no por paso. Y de protección de datos, que sobrevive a cualquier ampliación futura: el estado del orquestador está **fuera** del cifrado por tenant y tiene **retención propia de 90 días**; poner PII de categoría especial ahí crea una copia que no obedece a la política del expediente y elude el control primario de aislamiento.

Cuatro reglas operativas:

1. **Referencia canónica**: URI, hash del contenido, tipo MIME, tamaño, `tenant_id` y contexto de cifrado. El hash permite verificar integridad sin descargar dos veces y alimenta la cadena de auditoría.
2. **URLs prefirmadas de vida corta y alcance mínimo**: una operación y un objeto concretos, con expiración ajustada al paso. Se tratan como credenciales: no se registran en logs ni se propagan más allá del paso que las consume.
3. **Los resultados normalizados viajan; las respuestas crudas no.** El adaptador devuelve campos extraídos y puntuaciones; la respuesta cruda del proveedor se persiste como artefacto y se referencia.
4. **Ciclo de vida explícito**: se distingue el artefacto de evidencia —sellado, inmutable, con retención regulatoria— del artefacto intermedio —efímero, con política que lo elimina.

## Consecuencias

### Positivas

- Los tres límites dejan de ser una restricción práctica: el tamaño del estado es independiente del de los artefactos.
- El historial queda libre de PII de categoría especial, lo que simplifica la DPIA y el derecho de supresión.
- El cliente sube la imagen directamente, sin que el middleware sea cuello de banda ni almacene copias en tránsito.
- El hash de contenido da integridad verificable de extremo a extremo y enlaza con la cadena de auditoría.
- El crecimiento del historial se contiene, alejando el límite de 25.000 eventos.

### Negativas

- Latencia adicional por cada resolución de referencia, acumulable si varios pasos tocan la misma imagen.
- Ciclo de vida de artefactos que gestionar, con riesgo de referencias colgantes si borrado y retención se desalinean.
- Depuración menos directa: reproducir una ejecución exige acceso a los artefactos, con permisos y registro de acceso.
- Las URLs prefirmadas son credenciales portadoras con su propia superficie de riesgo.

### Neutras

- `ObjectStoragePort` expone `presign_put`, `presign_get`, `head`, `delete` y `set_lifecycle`, con adaptador local basado en sistema de archivos y firma simulada.
- La distinción entre `EvidenceStorePort` (sellado e inmutable) y `ObjectStoragePort` (operativo y efímero) es deliberada: son dos ciclos de vida distintos.

## Criterios de revisión

- **Si Cloud Workflows amplía sustancialmente el límite de 512 KB**, desaparece la restricción de viabilidad, pero **no** el argumento de protección de datos: la decisión se mantendría por el segundo motivo.
- **Si la latencia acumulada por resolución de referencias incumple el SLA**, la respuesta es caché de artefactos junto al cómputo o consolidación de pasos, no devolver contenido al estado.
- **Si aparecen referencias colgantes en producción**, hay que revisar la alineación entre ciclo de vida del almacén y retención del expediente.
- **Si una URL prefirmada se filtra en logs o en el estado**, se trata como incidente de seguridad y se reduce la ventana de expiración por defecto.
- **Si un proveedor externo exige recibir el binario en línea**, el adaptador asume la descarga y el envío, pero el estado sigue viendo solo la referencia.

## Referencias

- [Step Functions service quotas — payload de 256 KiB, historial de 25.000 eventos](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html)
- [Workflows quotas and limits — 512 KB acumulados por ejecución](https://docs.cloud.google.com/workflows/quotas)
- [Lambda quotas — payload síncrono de 6 MB, asíncrono de 1 MB](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [gcp-paridad-de-servicios §3, brecha 7](../referencias/gcp-paridad-de-servicios.md)
- [CLAUDE.md — convenciones transversales del repositorio](../../CLAUDE.md)
- [cumplimiento-normativo-y-estandares §B.6.3 — art. 25 GDPR, minimización](../referencias/cumplimiento-normativo-y-estandares.md)
