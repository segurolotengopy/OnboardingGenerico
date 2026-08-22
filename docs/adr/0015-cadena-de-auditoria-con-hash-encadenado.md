# ADR-0015 — Cadena de auditoría con hash encadenado sobre almacenamiento WORM, exportada fuera del historial del orquestador

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [ADR-0004](0004-orquestacion-hibrida-standard-express.md) · [ADR-0010](0010-revision-humana-construida-a-medida.md) · [ADR-0014](0014-el-middleware-es-encargado-del-tratamiento.md) · [12 — Retención y borrado](../12-retencion-y-borrado.md) · [13 — Observabilidad y SRE](../13-observabilidad-y-sre.md) · [11 — Cumplimiento normativo](../11-cumplimiento-normativo.md) |

## Contexto

Un supervisor financiero, años después de un onboarding, puede pedir la reconstrucción del proceso aplicado a un titular: qué evidencia se recogió, qué respondió cada proveedor, qué umbrales se aplicaron, quién revisó el caso y qué decidió. Su valor depende de que el registro sea **completo, atribuible e íntegro**.

Los plazos exigidos hacen inviable apoyarse en el historial del orquestador:

| Jurisdicción | Retención KYC |
|---|---|
| Paraguay | **5 años** desde la finalización de la relación comercial (art. 42 de la Res. SEPRELAD 70/2019; art. 18 de la Ley 1015/1997) |
| Bolivia | **10 años** por el art. 34.III de la Ley 393 para libros y documentos contables; el plazo del expediente KYC **no está confirmado** |
| México | **10 años** citado, sin confirmación en fuente primaria |
| UE | 5 a 10 años según el régimen aplicable |

Frente a eso, el historial de **Step Functions Standard se retiene 90 días** tras el cierre —reducible a 30 por solicitud—, y los workflows **Express no tienen retención propia**: requieren CloudWatch Logs, con política y coste propios ([ADR-0004](0004-orquestacion-hibrida-standard-express.md)). El desajuste es de dos órdenes de magnitud, así que **se requiere exportación explícita antes de que el historial expire**.

Hay un segundo requisito, distinto del de duración: la retención garantiza que el registro **existe**, no que **no haya sido alterado**. Un registro que un administrador puede reescribir sin dejar rastro no prueba nada ante un supervisor que investiga precisamente si hubo manipulación interna.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Retención de 5 a 10 años | El historial del orquestador (90 días) no sirve como registro |
| Detección de manipulación interna | La retención por sí sola no da integridad |
| Inmutabilidad frente a derecho de supresión | Lo escrito en WORM no se puede borrar dentro del periodo |
| Volumen de eventos por sesión | Escribir cada evento como objeto individual es caro |
| Portabilidad entre nubes | El mecanismo debe existir en AWS y GCP con semántica equivalente |
| Coste de almacenamiento a 10 años | Obliga a clases frías y a minimizar el contenido |

## Opciones consideradas

### Opción A — Historial del orquestador y logs de la nube como registro

**A favor**
- Sin desarrollo: los eventos ya se generan y se almacenan, con granularidad fina y sin instrumentar el código.
- Los logs de plano de control son un registro que los auditores conocen y aceptan.

**En contra**
- **Descalificador: 90 días frente a 5 o 10 años**, y los hijos Express ni siquiera tienen esos 90 días.
- Registra **transiciones de máquina de estados**, no **hechos de negocio**: «se ejecutó la tarea X» no es «se aplicó el umbral 0,92 al cotejo facial del titular Y con el proveedor Z».
- Acoplado al orquestador: refactorizarlo altera un registro histórico que debería ser estable, y el historial de Cloud Workflows no es equivalente.
- Sin integridad verificable: quien escribe en el grupo de logs puede alterar su contenido.

### Opción B — Tabla de auditoría en la base de datos operativa

**A favor**
- Consultable de inmediato por sesión, tenant o actor, con los mecanismos existentes.
- Coste de desarrollo bajo: reutiliza el repositorio y sus adaptadores, y se porta sin fricción.
- Queda bajo el cifrado por tenant y bajo la política de retención del expediente.

**En contra**
- **Sin inmutabilidad**: quien tiene permiso de escritura puede alterar o borrar entradas. Es exactamente el escenario que el registro debe poder descartar.
- Coste elevado de mantener 10 años en un almacén operativo, cuyo rendimiento además se degrada con el volumen.
- Un supervisor puede cuestionar el valor probatorio de un registro que el propio operador controla.

### Opción C — Eventos con hash encadenado sellados en WORM

Cada hecho auditable se emite como evento estructurado que incluye el **hash del evento anterior de la misma sesión**, formando una cadena. Los eventos se agregan por sesión o por ventana temporal y se sellan en **S3 Object Lock** o **GCS Bucket Lock**, con retención por jurisdicción.

**A favor**
- **Integridad verificable de forma independiente**: alterar un evento invalida el hash de todos los posteriores, y ocultarlo exigiría reescribir la cadena, lo que el WORM impide. Retención e integridad se refuerzan: ninguna basta sola.
- Registra **hechos de negocio**, así que sobrevive a una refactorización del orquestador.
- La retención se configura con las políticas de la plataforma, no con lógica de aplicación.
- Se porta con riesgo bajo: `AuditLogPort` tiene semántica equivalente en S3 y GCS, con adaptador local que verifica la cadena, y combina con el registro de decisiones de la revisión humana ([ADR-0010](0010-revision-humana-construida-a-medida.md)).

**En contra**
- Hay que instrumentar explícitamente qué es un hecho auditable; lo que no se emite, no existe.
- **La inmutabilidad choca con el art. 17 del GDPR**: lo escrito en WORM no se puede borrar dentro del periodo.
- La cadena por sesión obliga a serializar la emisión o a aceptar reordenación con número de secuencia.
- Coste de almacenamiento a 10 años, y un fallo de sellado deja huecos que hay que detectar y explicar.

### Opción D — Anclaje en un servicio externo de sellado o en una cadena de bloques

**A favor**
- La prueba de integridad no depende del operador ni de su proveedor de nube: el argumento más fuerte frente a la manipulación interna.
- El sellado temporal cualificado tiene valor probatorio reconocido en algunos marcos.
- Coste marginal bajo si solo se ancla un hash raíz periódico.

**En contra**
- **Ningún regulador del alcance lo exige**: se paga complejidad por un requisito inexistente.
- Introduce un tercero en un flujo de cumplimiento crítico, con su disponibilidad como dependencia.
- El anclaje periódico no protege los eventos posteriores al último anclaje: no elimina la necesidad de WORM.

## Decisión

**Se adopta la opción C: eventos de auditoría inmutables con hash encadenado, sellados en almacenamiento WORM, exportados fuera del historial del orquestador.**

El argumento combina dos propiedades que ninguna otra opción reúne. La **retención de 90 días es insuficiente por dos órdenes de magnitud** frente a los 5 a 10 años exigidos, y los hijos Express no tienen retención propia: hay que exportar de todos modos. Y una vez que hay que construir el registro, añadir el encadenamiento cuesta poco y aporta lo que la retención sola no da: **detectar manipulación posterior, incluso por parte de quien tiene permisos de escritura**.

Cinco reglas:

1. **Hechos de negocio, no transiciones de orquestador.** Cada evento lleva tipo, `tenant_id`, `session_id`, número de secuencia, marca temporal, actor, versión de la especificación aplicada, proveedor y versión, umbral, resultado y el **hash del evento anterior de la misma sesión**.
2. **Sin datos personales en el registro.** Los artefactos y valores extraídos se referencian por puntero y hash de contenido ([ADR-0011](0011-punteros-a-objetos-en-lugar-de-payloads.md)). El registro prueba **qué ocurrió**, no **qué decía el documento**. Eso hace compatible la inmutabilidad con el derecho de supresión: se destruye el artefacto y la clave del tenant, y la cadena sigue siendo verificable porque solo contiene hashes.
3. **La exportación es continua**, no un volcado antes del día 90. El historial del orquestador queda como herramienta de depuración, nunca como registro de cumplimiento.
4. **La retención WORM se configura por jurisdicción** conforme a la matriz de [12](../12-retencion-y-borrado.md), y la fija el responsable del tratamiento ([ADR-0014](0014-el-middleware-es-encargado-del-tratamiento.md)).
5. **La verificación de la cadena es una operación de producto**: una comprobación periódica recorre las sesiones cerradas y alerta ante cualquier ruptura o hueco de secuencia.

Sobre el conflicto con el art. 17 del GDPR, la resolución es la de [12](../12-retencion-y-borrado.md): la excepción de obligación legal cubre **lo necesario**, no todo lo capturado; el mecanismo es **bloqueo y no uso**, no borrado; y el reloj arranca **al terminar la relación**. La separación entre expediente KYC —retenible— y datos biométricos —minimizables— es lo que hace compatibles ambas obligaciones.

Se descarta la opción D por no ser exigida por ningún regulador del alcance, sin perjuicio de que la estructura de cadena permita añadirla después sin rediseño.

## Consecuencias

### Positivas

- El registro sobrevive a los plazos de todas las jurisdicciones, con independencia del orquestador.
- Una manipulación posterior es detectable aunque el atacante tenga permisos de escritura.
- Es estable frente a refactorizaciones porque describe hechos de negocio.
- La ausencia de datos personales permite ejercer el derecho de supresión sin romper la verificabilidad.

### Negativas

- Hay que instrumentar qué es hecho auditable; una omisión produce un hueco que solo se descubre en una auditoría.
- La cadena por sesión exige orden: o se serializa la emisión, o se reconstruye con número de secuencia.
- Coste de almacenamiento a 5 o 10 años, mitigable con clases frías pero no eliminable.
- La retención bloqueada es irreversible: un error de configuración no se puede deshacer.

### Neutras

- La publicación de una especificación, la resolución de un caso de revisión y el acceso de soporte transfronterizo entran en la misma cadena.
- El historial del orquestador conserva su valor como herramienta de depuración durante sus 90 días.
- La estructura de hashes deja abierta la posibilidad de anclaje externo si un regulador lo exigiera.

## Criterios de revisión

- **Si se verifica el plazo de conservación del expediente KYC en Bolivia** —el art. 39(VII) remite al art. 66, no recuperable— hay que ajustar la retención WORM.
- **Si un regulador exige sellado temporal cualificado o anclaje externo**, la opción D se incorpora sin rediseñar la cadena.
- **Si la verificación periódica detecta rupturas de cadena**, se trata como incidente de seguridad.
- **Si el coste a largo plazo excede el presupuesto**, la palanca es reducir el contenido del evento y usar clases más frías, nunca acortar la retención bajo el mínimo regulatorio.
- **Si AWS o Google amplían la retención del historial** hasta cubrir los plazos KYC, el argumento de duración desaparece, pero **no** el de integridad ni el de estabilidad.

## Referencias

- [Step Functions service quotas — retención de 90 días, 25.000 eventos](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html)
- [aws-arquitecturas-de-referencia — verificación de cifras, punto 5](../referencias/aws-arquitecturas-de-referencia.md)
- [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html) · [GCS Bucket Lock](https://cloud.google.com/storage/docs/bucket-lock)
- [cumplimiento-normativo-y-estandares §C.11 — retención y su conflicto con el derecho de supresión](../referencias/cumplimiento-normativo-y-estandares.md)
- [cumplimiento-normativo-y-estandares §B.9.2 y §B.8.1](../referencias/cumplimiento-normativo-y-estandares.md)
- [Reglamento (UE) 2016/679, art. 17 — EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
