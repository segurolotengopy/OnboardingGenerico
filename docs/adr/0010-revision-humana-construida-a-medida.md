# ADR-0010 — Revisión humana construida a medida en ambas nubes, con log de decisiones WORM

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [ADR-0004](0004-orquestacion-hibrida-standard-express.md) · [ADR-0015](0015-cadena-de-auditoria-con-hash-encadenado.md) · [ADR-0014](0014-el-middleware-es-encargado-del-tratamiento.md) · [10 — Multinube](../10-multicloud-aws-gcp.md) · [11 — Cumplimiento normativo](../11-cumplimiento-normativo.md) |

## Contexto

Ningún flujo de onboarding remoto se resuelve íntegramente de forma automática. Documento desgastado, cotejo facial en zona gris, resultado PAD no concluyente, coincidencia parcial en listas de sanciones o cliente marcado como persona expuesta políticamente se derivan a una persona. La derivación no es un fallo: es un control implícito en el enfoque basado en riesgo del GAFI y explícito en los regímenes ampliados de debida diligencia.

Hay además una obligación estructural: en Bolivia, el art. 32(II) del Instructivo UIF prohíbe delegar en terceros la ejecución de la debida diligencia del cliente, de modo que la decisión debe retenerla la entidad ([ADR-0014](0014-el-middleware-es-encargado-del-tratamiento.md)). El sistema **necesita** un punto de decisión humana bajo control del cliente, con rastro suficiente para que un supervisor verifique quién decidió qué, cuándo y con qué evidencia a la vista.

El hecho que resuelve la comparación es que **las dos nubes abandonaron su producto gestionado de revisión humana**: **SageMaker A2I** está *«no longer open to new customers»*; **Document AI Human-in-the-Loop** se apagó el **16 de enero de 2025**; **Vertex AI Data Labeling**, el **3 de octubre de 2024**, con recomendación oficial de contratar un partner.

La investigación de paridad añade dos observaciones que conviene retener: **esto simplifica el diseño**, porque no hay servicio gestionado que elegir en ninguna nube y la asimetría desaparece; y A2I nunca dio bien la trazabilidad regulatoria, porque sus plantillas de tarea están pensadas para **etiquetado de aprendizaje automático**, no para decisiones de cumplimiento.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Ambas nubes retiraron su HITL gestionado | No hay opción de comprar dentro de la nube |
| Trazabilidad regulatoria de la decisión | El registro debe ser inmutable, atribuible y conservable por años |
| La decisión la retiene la entidad cliente | El flujo debe admitir revisores del cliente |
| Coste de construir UI, colas, asignación y escalado | Es un producto dentro del producto |
| Esperas largas en el orquestador | Exceden las 12 h por defecto de los callbacks de Cloud Workflows |
| Datos de categoría especial en pantalla | Minimización, control de acceso y registro de visualización |

## Opciones consideradas

### Opción A — SageMaker A2I en AWS, partner o desarrollo propio en GCP

**A favor**
- En cuentas con acceso previo, la integración con Step Functions es directa y ahorra construir colas y asignación.
- Interfaz de trabajador ya existente, con gestión de fuerza de trabajo privada.
- Sin desarrollo inicial en la nube de referencia.

**En contra**
- **Descalificador: está cerrado a nuevos clientes.** Construir sobre un servicio que no admite altas es asumir deuda técnica el primer día.
- **No sirve para trazabilidad de cumplimiento**: el artefacto que produce no es un registro de decisión con actor, evidencia mostrada, criterio aplicado y sello temporal inmutable.
- Reproduce la asimetría entre nubes justo en el control donde el supervisor mira con más atención.
- La investigación es explícita: si una implementación AWS usa A2I, **ya tiene deuda técnica con independencia del portaje**.

### Opción B — Plataforma comercial de revisión de casos

Contratar una plataforma de gestión de casos o un partner y externalizar cola, interfaz y flujo de trabajo.

**A favor**
- Funcionalidad madura sin desarrollo: asignación, escalado, SLA, informes, gestión de turnos.
- Portable entre nubes por ser externa a ambas.
- Reduce el alcance del producto a lo que lo diferencia.

**En contra**
- **Un subencargado que ve datos biométricos y documentales de categoría especial**, que hay que declarar, evaluar y cubrir con cláusulas contractuales tipo y evaluación de transferencias ([ADR-0013](0013-residencia-de-datos-y-regionalizacion.md)). Es el subencargado que un cliente bancario europeo cuestiona antes que ninguno.
- Sacar la evidencia del perímetro rompe la cadena de custodia: el registro viviría en un sistema de terceros con su propia retención y su propio formato.
- Las plataformas genéricas no modelan lo que aquí importa: qué evidencia exacta se mostró al revisor al decidir.
- Coste por usuario o por caso, con integración bidireccional no trivial con el orquestador.

### Opción C — Servicio propio en ambas nubes, con log de decisiones WORM

`HumanReviewPort` como servicio del producto: cola con prioridad, asignación y escalado, interfaz con la evidencia del caso, y **log de decisiones en almacenamiento inmutable** —S3 Object Lock en AWS, GCS Bucket Lock en GCP.

**A favor**
- **No hay asimetría que gestionar**: se construye una vez y el mismo código corre en las dos nubes; solo cambia el adaptador de persistencia y de WORM. Paradójicamente, es la opción que **elimina** riesgo de portabilidad.
- El registro se diseña para lo que se necesita: revisor, rol, tenant, caso, **hash de la evidencia exhibida**, criterio, versión de la especificación vigente, resultado y sello temporal. Ningún producto de etiquetado lo produce.
- El WORM cumple mejor que A2I: la inmutabilidad la impone la plataforma, no la aplicación.
- Los datos no salen del perímetro del middleware ni de la región de residencia.
- Permite modelar el requisito boliviano con precisión: revisores del cliente, con la decisión final atribuida a la entidad.
- La minimización se controla en la propia interfaz y la visualización queda registrada.

**En contra**
- Es un producto dentro del producto: cola, asignación, escalado, SLA, autenticación de revisores, interfaz e informes.
- Introduce una interfaz de usuario en un sistema que por lo demás es API pura, con su pila, su ciclo de seguridad y su accesibilidad.
- La operación 24×7 de la cola y sus SLA pasa a ser responsabilidad del producto o del cliente.
- Riesgo de reimplementar mal lo que un BPM maduro ya resuelve: enrutamiento, balanceo entre revisores, gestión de ausencias.

## Decisión

**Se adopta la opción C: `HumanReviewPort` se construye a medida en ambas nubes, con el log de decisiones en almacenamiento WORM.**

El argumento decisivo no es de preferencia: **no hay nada que comprar dentro de ninguna de las dos nubes**. La comparación real es entre construir y externalizar a un tercero, y ahí pesa la trazabilidad: el artefacto que este sistema debe producir es un **registro de decisión de cumplimiento**, no una etiqueta de entrenamiento.

El efecto sobre la arquitectura multinube merece decirse: construir a medida **elimina** una brecha de paridad en lugar de gestionarla. `HumanReviewPort` es de riesgo bajo en el portaje precisamente porque nadie lo ofrece gestionado.

Cinco requisitos del registro de decisión:

1. **Inmutabilidad por plataforma**: retención bloqueada; la aplicación no puede borrar ni sobrescribir dentro del periodo.
2. **Atribución completa**: revisor, rol, organización —middleware o entidad cliente—, tenant y caso.
3. **Evidencia exhibida**: hash de los artefactos y resultados visibles al decidir. Sin esto no se puede reconstruir por qué la decisión fue razonable.
4. **Contexto de proceso**: versión de la especificación vigente ([ADR-0007](0007-registro-de-capacidades-dirigido-por-especificacion.md)) y umbrales aplicados.
5. **Encadenamiento**: cada entrada se integra en la cadena de auditoría con hash encadenado ([ADR-0015](0015-cadena-de-auditoria-con-hash-encadenado.md)), de modo que una manipulación posterior sea detectable aunque el atacante tenga permiso de escritura.

La espera del orquestador se resuelve con `SagaPort.suspend_until(correlation_id)`: en AWS con `.waitForTaskToken` en el padre Standard, con horizonte de hasta un año; en GCP, persistiendo estado, terminando la ejecución y relanzándola, porque los callbacks de Cloud Workflows tienen **12 horas por defecto**, **un solo slot pendiente por endpoint** y **sin heartbeat**, y una revisión que cruce un fin de semana no cabe.

## Consecuencias

### Positivas

- Un único servicio de revisión, idéntico en las dos nubes, sin asimetría que explicar en una DPIA.
- Registro de decisión diseñado para auditoría regulatoria, no adaptado desde una herramienta de etiquetado.
- Los datos de categoría especial no salen del perímetro ni de la región del despliegue.
- Admite revisores de la entidad cliente, que es lo que exige la posición de encargado y, en Bolivia, el art. 32(II).
- La minimización se aplica en la interfaz y queda registrada.

### Negativas

- Alcance de desarrollo considerable: cola, asignación, escalado, interfaz, autenticación e informes.
- Se introduce una interfaz de usuario con su propia superficie de seguridad y su ciclo de mantenimiento.
- Operación y SLA de la cola pasan a negociarse con cada cliente.
- Riesgo de reimplementar de forma inferior el enrutamiento y el balanceo que un BPM maduro ya resuelve.

### Neutras

- El WORM se configura por Terraform con retención por jurisdicción; la política la fija el responsable del tratamiento ([ADR-0014](0014-el-middleware-es-encargado-del-tratamiento.md)).
- El adaptador local resuelve casos desde la línea de comandos, lo que permite probar el flujo completo sin infraestructura.

## Criterios de revisión

- **Si alguna nube publica un HITL orientado a decisiones de cumplimiento** —con registro atribuible, evidencia exhibida y almacenamiento inmutable—, procede reevaluar la construcción propia.
- **Si el volumen de casos supera la capacidad del equipo**, la respuesta es un partner de operación con revisores, no externalizar el sistema de registro: la cadena de custodia debe permanecer en el perímetro.
- **Si el tiempo medio de resolución excede el horizonte sostenible en GCP**, hay que consolidar el patrón de relanzamiento como modelo principal en ambas nubes.
- **Si un cliente exige integrar su propio BPM**, se admite siempre que el registro de decisión se emita igualmente a la cadena de auditoría del middleware: el BPM sería interfaz, no sistema de registro.
- **Si el máximo real del `timeout` de `events.await_callback` resulta superior a 12 h** —dato hoy **no verificado**—, procede revisar si el relanzamiento sigue siendo necesario para revisiones cortas.

## Referencias

- [gcp-paridad-de-servicios §3, brechas 3 y 7](../referencias/gcp-paridad-de-servicios.md)
- [Amazon SageMaker Augmented AI (A2I)](https://aws.amazon.com/sagemaker-ai/groundtruth/)
- [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html) · [GCS Bucket Lock](https://cloud.google.com/storage/docs/bucket-lock)
- [Wait using callbacks | Workflows](https://docs.cloud.google.com/workflows/docs/creating-callback-endpoints)
- [cumplimiento-normativo-y-estandares §B.8.2 — art. 32(II) Instructivo UIF Bolivia](../referencias/cumplimiento-normativo-y-estandares.md)
