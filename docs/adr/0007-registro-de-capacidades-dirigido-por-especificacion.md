# ADR-0007 — Registro de capacidades dirigido por especificación, con versionado inmutable

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [04 — Motor de composición](../04-motor-de-composicion.md) · [02 — Arquitectura](../02-arquitectura.md) · [ADR-0001](0001-arquitectura-hexagonal-multinube.md) · [ADR-0015](0015-cadena-de-auditoria-con-hash-encadenado.md) · [12 — Retención y borrado](../12-retencion-y-borrado.md) |

## Contexto

El producto se define por su capacidad de **componer dinámicamente** los pasos de un onboarding según el tenant, el país y el tipo de documento. Esa promesa se juega en un punto concreto: qué hace falta para que un cliente nuevo, con un país nuevo y un documento nuevo, entre en producción.

La variabilidad es amplia. Un banco mexicano debe aplicar prueba de vida certificada con detección de ataques de inyección desde la reforma de la CNBV del 1 de julio de 2026; una fintech boliviana opera sin marco de onboarding remoto y debe consultar al SEGIP; una entidad paraguaya aplica el régimen ampliado del art. 28 de la Resolución SEPRELAD 70/2019 a personas expuestas políticamente. El mismo puerto se invoca con umbrales, obligatoriedad y orden distintos.

Si esa variabilidad se expresa en código desplegado, cada cliente nuevo es una rama, cada país nuevo un despliegue y cada ajuste de umbral pasa por el ciclo completo de integración continua: exactamente el estado del que el producto pretende sacar a sus clientes.

Hay además una restricción de auditoría. Un supervisor puede preguntar, sobre un expediente de hace dos años, **qué proceso exacto se aplicó a ese titular**. La respuesta no puede ser «la versión del código desplegada entonces», porque esa versión ya no es recuperable ni verificable. Tiene que ser un artefacto identificable, inmutable y conservado.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Variabilidad por tenant, país y documento | Codificarla como ramas de código no escala |
| Ciclo de despliegue frente a velocidad comercial | Un país nuevo no puede requerir una versión del middleware |
| Auditoría de qué proceso se aplicó | La configuración vigente debe ser artefacto inmutable y recuperable |
| Configuración como dato = superficie nueva | Un cambio de datos puede alterar controles sin revisión de código |
| Verificación estática | El código desplegado se verifica en compilación; los datos, no |
| Depuración de un motor genérico | Un fallo de interpretación es más difícil de diagnosticar |

## Opciones consideradas

### Opción A — Configuración en código desplegado

Clases de estrategia por jurisdicción, constantes de umbral, ramas explícitas. Un país nuevo es un pull request y un despliegue.

**A favor**
- Verificación completa en compilación: `mypy` estricto comprueba tipos, exhaustividad y contratos de puerto.
- Un solo canal de cambio de comportamiento, con el flujo de revisión habitual.
- Depuración directa: una traza de pila apunta a la línea que decidió.
- La trazabilidad se apoya en el control de versiones, que ya existe.

**En contra**
- **No escala al eje comercial**: el tiempo hasta producción de un cliente queda atado al ciclo de ingeniería.
- Ajustar un umbral —que el responsable del tratamiento puede exigir cambiar ([ADR-0014](0014-el-middleware-es-encargado-del-tratamiento.md))— requiere desplegar el middleware, lo que es desproporcionado y contractualmente incómodo.
- El código acumula ramas por jurisdicción imposibles de leer y de retirar.
- Reconstruir qué se aplicó a un expediente antiguo exige recuperar y ejecutar mentalmente una versión histórica.

### Opción B — Motor de reglas de propósito general

Un motor de reglas o lenguaje embebido, con reglas escritas por el equipo de implantación.

**A favor**
- Máxima expresividad: casi cualquier requisito se resuelve sin tocar el producto.
- Cambio en caliente, sin despliegue.
- Traslada el trabajo de configuración fuera del equipo de ingeniería.

**En contra**
- **Expresividad ilimitada es superficie de ataque ilimitada.** Una regla arbitraria puede desactivar un control obligatorio, filtrar datos entre pasos o construir un bucle infinito. En un sistema que decide sobre datos biométricos, es inaceptable.
- La validación estática es esencialmente imposible: no se puede garantizar que una regla arbitraria termine, respete los contratos o no omita un control exigido.
- Los motores de reglas acumulan lógica de negocio sin tipos, sin pruebas y sin refactorización, en manos de quienes no la mantienen.
- El comportamiento emerge de la interacción de reglas, no de una secuencia legible.

### Opción C — Registro de capacidades más especificaciones declarativas versionadas de forma inmutable

Dos artefactos de datos. El **registro de capacidades** declara *qué* hace una unidad atómica —`ocr.document.v1`, `extraction.semantic.v1`— mediante contrato de entrada y salida con esquema, aplicabilidad por país y documento, y semántica (idempotencia, coste, latencia). Declara qué hace, **no quién lo hace**. La **especificación de flujo** declara, para un tenant, país y documento, qué capacidades se invocan, en qué orden, con qué umbrales y con qué condiciones de derivación; es declarativa y **no admite código arbitrario**. Ambos se validan antes de publicarse, se compilan a un plan de ejecución y se publican con **versionado inmutable**.

**A favor**
- **La variabilidad se resuelve sin desplegar código** en los casos que dominan el trabajo comercial: cambiar un umbral, reordenar pasos, cambiar de proveedor entre los ya integrados, añadir un país con capacidades existentes, añadir un documento cuando la plantilla de extracción es dato.
- El poder expresivo está **acotado por diseño**: se componen capacidades existentes, no se introduce comportamiento nuevo. Eso es lo que la hace validable.
- El versionado inmutable responde la pregunta del auditor: el expediente referencia una versión concreta, conservada y verificable por hash.
- Los contratos con esquema hacen que un cambio de contrato de un proveedor rompa en validación y no en producción.
- El despliegue puede ser canario y reversible con métricas objetivas, granularidad que el despliegue de código no ofrece.

**En contra**
- Construir el motor —resolución, validación, compilación, versionado, promoción— es trabajo real que no aporta valor visible al cliente final.
- Se pierde la verificación en compilación sobre lo que ahora es dato; la validación que la reemplaza es código que puede tener bugs.
- Aparece un **segundo canal de cambio de comportamiento** que debe someterse a control equivalente al del código.
- Depurar el motor genérico es más difícil: el comportamiento resulta de la interacción entre especificación, registro y plan compilado.

## Decisión

**Se adopta la opción C.** El argumento decisivo es que la variabilidad de este producto es **su función**, no un accidente: un middleware cuyo valor es componer capacidades por tenant y país no puede tener la composición congelada en el binario.

La opción B se descarta por seguridad, no por gusto: en un sistema que trata datos de categoría especial y que implementa controles exigidos por reguladores financieros, la configuración **no puede tener poder de cómputo arbitrario**. La expresividad acotada es la propiedad que permite validar antes de publicar.

Cuatro reglas la hacen sostenible:

1. **Inmutabilidad estricta.** Una versión publicada nunca se modifica; un cambio produce una versión nueva. Una especificación retirada **no se elimina** mientras exista un expediente que la referencie: es parte de la evidencia de qué proceso se aplicó a ese titular.
2. **Validación previa obligatoria**, incluida la comprobación de que las capacidades referenciadas existen, que los contratos encajan y que los controles obligatorios por jurisdicción están presentes.
3. **El cambio de configuración es un cambio auditado**: publicar emite un evento en la cadena de auditoría con actor, versión previa, versión nueva y hash del contenido ([ADR-0015](0015-cadena-de-auditoria-con-hash-encadenado.md)).
4. **Honestidad sobre los límites.** Integrar un proveedor nuevo, definir una capacidad nueva o cambiar la máquina de estados de la sesión **sí** requieren desplegar código ([04 §8.3](../04-motor-de-composicion.md)).

## Consecuencias

### Positivas

- Un país o documento nuevo cubierto con capacidades existentes entra en producción sin versión del middleware.
- Cada expediente referencia una versión identificable y conservada: la pregunta del auditor tiene respuesta exacta.
- La promoción canaria con reversión por métricas —derivación a revisión humana, `InconclusiveResult`, latencia, tasa de rechazo, coste por sesión— da un control de riesgo más fino que el despliegue de código.
- El registro documenta el sistema por construcción: el contrato es el mismo artefacto que ejecuta.

### Negativas

- El motor de composición es un componente propio, complejo y crítico, que no se puede externalizar a una biblioteca.
- La validación reemplaza a la verificación en compilación, y una laguna se convierte en fallo en producción.
- El segundo canal exige controles de autorización y revisión propios, con riesgo de tratarse con menos rigor que un pull request.
- Las especificaciones retiradas se acumulan mientras haya expedientes vivos.

### Neutras

- Las especificaciones viven en `FlowSpecRepositoryPort`, que se porta sin fricción (DynamoDB + S3 en AWS, Firestore + GCS en GCP) y tiene adaptador local que carga YAML del repositorio.
- El ciclo de vida es explícito: borrador, validada, preparada, canaria, activa, obsoleta, retirada.

## Criterios de revisión

- **Si la proporción de solicitudes que exigen desplegar código supera de forma sostenida a las que se resuelven con especificación**, el registro está mal granulado y hay que revisar su descomposición.
- **Si aparece un requisito recurrente que la especificación no puede expresar** sin cómputo arbitrario, la respuesta es una capacidad nueva, no ampliar el lenguaje. Si ocurre más de dos o tres veces por trimestre, procede reabrir la decisión.
- **Si un incidente se origina en una publicación de configuración no revisada**, hay que endurecer el segundo canal hasta equipararlo al del código.
- **Si el volumen de especificaciones retiradas se vuelve inmanejable**, hay que definir archivado en frío que preserve la verificabilidad por hash.

## Referencias

- [Build a dynamic workflow orchestration engine with Amazon DynamoDB and AWS Lambda — AWS Database Blog](https://aws.amazon.com/blogs/database/build-a-dynamic-workflow-orchestration-engine-with-amazon-dynamodb-and-aws-lambda/)
- [aws-arquitecturas-de-referencia — Ficha 6](../referencias/aws-arquitecturas-de-referencia.md)
- [cumplimiento-normativo-y-estandares §B.7.4, §B.8.2 y §B.9.2](../referencias/cumplimiento-normativo-y-estandares.md)
- [04 — Motor de composición §3 y §8](../04-motor-de-composicion.md)
