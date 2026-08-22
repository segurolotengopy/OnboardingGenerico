# ADR-0004 — Orquestación híbrida: Standard como padre y Express como hijos anidados

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [07 — Orquestación](../07-orquestacion.md) · [ADR-0011](0011-punteros-a-objetos-en-lugar-de-payloads.md) · [ADR-0015](0015-cadena-de-auditoria-con-hash-encadenado.md) · [ADR-0010](0010-revision-humana-construida-a-medida.md) · [20 — Fe de erratas](../20-fe-de-erratas-del-spec-original.md) |

## Contexto

Una sesión de onboarding combina dos regímenes temporales incompatibles: **pasos automatizados de segundos** (OCR, verificación de dígitos de control de la MRZ, extracción por LLM, cotejo facial 1:1, cribado AML, *scoring*) y **esperas de horas o días** (revisión humana, escalado a cumplimiento, respuesta asíncrona de un registro gubernamental). Además hay acciones **no idempotentes** cuyo doble disparo tiene consecuencias reales: crear la cuenta, notificar el alta, emitir el veredicto que la entidad usará en su expediente KYC.

Las cuotas verificadas de Step Functions que condicionan el diseño:

| Cuota | Standard | Express |
|---|---|---|
| Duración máxima | **1 año** | **5 minutos** |
| Retención de historial | **90 días** tras el cierre (reducible a 30 por solicitud) | Requiere CloudWatch Logs para cualquier inspección |
| Tamaño máximo de historial | **25.000 eventos** por ejecución | Sin límite |
| Payload de entrada/salida | **256 KiB** (UTF-8) | **256 KiB** (UTF-8) |
| Semántica | *exactly-once* | asíncrono *at-least-once* / síncrono *at-most-once* |
| Integraciones | Todas | Todas **excepto** `.sync` y `.waitForTaskToken` |
| Distributed Map / Activities | Soportados | **No soportados** |

Dos precisiones importan. El blog de AWS afirma que Standard no tiene límite de duración; **la documentación oficial fija 1 año** y prevalece. Y el límite de **25.000 eventos de historial por ejecución** no aparecía en el spec original: un flujo con reintentos o con un bucle sobre N documentos puede agotarlo.

**Sobre el «ahorro del 72,5 %» del spec original: la cifra no existe en ninguna fuente y no debe usarse.** Las cifras reales del blog de AWS, sobre un workflow de ejemplo ejecutado 1.000 veces, son **98 %** (Standard puro → Express puro) y **~52 %** (Standard puro → patrón anidado). Ninguna es transferible sin cálculo propio: el ahorro depende del número de transiciones y de la duración media del flujo concreto.

**La fórmula real de coste**, con los precios publicados en esa fuente:

- **Standard**: `coste = nº de transiciones de estado × 0,000025 USD`. El tiempo de espera **no se factura**: una espera humana de días cuesta lo mismo que una de segundos.
- **Express**: `coste = (0,000001 USD por petición) + (duración redondeada a 100 ms × tarifa de GB-hora del bloque de memoria, en bloques de 64 MB)`.
- **Anidado**: la suma, con **cero coste adicional por arrancar un workflow hijo**.

En el ejemplo del blog: Standard puro con 17 transiciones, `17 × 1.000 × 0,000025 = 0,42 USD`; Express puro con 11.300 ms de media, `(0,000001 + 0,0000117746) × 1.000 = 0,01 USD`; anidado con el padre reducido a 8 transiciones, `0,20 USD` de padre más `0,0002 USD` de hijos. **La mitad del ahorro del patrón anidado vino de bajar de 17 a 8 transiciones**, no de la anidación en sí. Esa es la palanca; el porcentaje hay que medirlo, no copiarlo.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Esperas de días por revisión humana | Exige `.waitForTaskToken`, que Express no soporta |
| Acciones no idempotentes | Exigen *exactly-once*, que solo da Standard |
| Volumen de pasos automatizados | Standard cobra por transición: el coste crece con la granularidad |
| Trazabilidad KYC/AML de largo plazo | 90 días son insuficientes; Express ni siquiera los tiene |
| Límite de 25.000 eventos | Penaliza flujos con muchos reintentos o bucles |
| Portabilidad a Cloud Workflows | Sus callbacks tienen 12 h por defecto y un solo slot pendiente |

## Opciones consideradas

### Opción A — Standard puro

Toda la máquina de estados en Standard, incluidos los pasos automatizados de grano fino.

**A favor**
- *Exactly-once* en todo el flujo, sin excepciones que razonar.
- `.waitForTaskToken`, `.sync`, Distributed Map y Activities disponibles en cualquier punto.
- Historial de 90 días en un único árbol coherente, con un solo modelo mental.

**En contra**
- Coste lineal en transiciones. Un flujo eKYC detallado supera con facilidad las 17 del ejemplo, y la factura escala con el volumen.
- Presiona hacia estados de grano grueso para ahorrar, degradando la observabilidad justo donde más se necesita.
- El límite de **25.000 eventos** se acerca en flujos con reintentos sobre varios documentos.

### Opción B — Express puro

Todo en Express, con la espera humana resuelta fuera del orquestador: persistir estado, terminar y relanzar.

**A favor**
- El coste más bajo de las tres: en el ejemplo, 98 % menos que Standard puro.
- Sin límite de tasa de transiciones (hasta 100.000 por segundo) ni de tamaño de historial.

**En contra**
- **Descalificador: 5 minutos de duración máxima.** Ninguna revisión humana cabe.
- ***At-least-once***: cualquier acción no idempotente puede ejecutarse dos veces. Crear dos cuentas o emitir dos veredictos KYC es un incidente regulatorio.
- Sin `.waitForTaskToken`, `.sync`, Distributed Map ni Activities.
- **Sin retención de historial propia**: la trazabilidad depende de CloudWatch Logs. Para KYC/AML es el peor punto de partida.
- Fragmentar el flujo en ejecuciones sueltas traslada la correlación a la aplicación y multiplica los puntos donde puede perderse la cadena de auditoría.

### Opción C — Híbrida: Standard padre con hijos Express anidados

El padre conserva esperas largas, acciones no idempotentes y la decisión final; los tramos automatizados de alta frecuencia se agrupan en hijos Express.

**A favor**
- Cada régimen temporal en el motor adecuado: garantías donde importan, coste por duración donde el trabajo es rápido.
- Reduce transiciones facturadas del padre al colapsar cadenas de `Pass` y `Choice` dentro del hijo, y **arrancar un hijo no consume transición facturada**.
- Cada hijo es un límite natural de idempotencia, exigible y verificable.
- Contiene el crecimiento del historial del padre, alejando el límite de 25.000 eventos.

**En contra**
- Dos tipos de workflow que mantener, probar y observar, con reglas distintas sobre qué vive en cada uno.
- El historial de los hijos **solo existe en CloudWatch Logs**, con coste y retención propios.
- Colocar mal un paso no idempotente en un hijo reintroduce el riesgo de doble ejecución de forma silenciosa.
- El mapeo a Cloud Workflows es menos directo: allí no hay distinción equivalente de modelos de facturación.

## Decisión

**Se adopta la opción C.** El argumento decisivo es que las esperas humanas de días y las acciones no idempotentes **exigen** Standard, y eso no admite negociación en un flujo KYC. Siendo Standard obligatorio en el padre, la única variable económica es cuántas transiciones se facturan en él: la anidación permite bajar esa cuenta sin perder garantías, y **colapsar transiciones triviales del padre es la palanca principal**.

Tres reglas de frontera:

1. **Todo lo no idempotente vive en el padre Standard**: alta de cuenta, notificación, emisión del veredicto, escritura de eventos de auditoría sellados.
2. **Todo lo que vive en un hijo Express es idempotente por construcción**, con clave derivada de `session_id` + `step_id` y escrituras condicionales.
3. **Ningún paso que requiera `.waitForTaskToken`, `.sync`, Distributed Map o Activities entra en un hijo Express.**

Sobre el coste, la regla es explícita: **no se cita ningún porcentaje de ahorro heredado**. Se aplica la fórmula al flujo real de cada tenant, con su número medido de transiciones y su duración media.

Consecuencia obligada, tratada en [ADR-0015](0015-cadena-de-auditoria-con-hash-encadenado.md): dado que el historial del padre se retiene **90 días** y el de los hijos no existe fuera de CloudWatch Logs, la trazabilidad KYC/AML **no puede apoyarse en el historial del orquestador**.

## Consecuencias

### Positivas

- Esperas humanas de días sin consumir cómputo y sin coste por el tiempo de espera.
- *Exactly-once* garantizado donde el negocio lo necesita.
- Coste del orquestador gobernable mediante una variable de diseño observable: las transiciones del padre.
- La idempotencia obligatoria en los hijos mejora la robustez general, incluida la reanudación tras fallo.

### Negativas

- Dos modelos de ejecución con reglas distintas: más carga cognitiva y más superficie de error de diseño.
- Coste y gestión adicionales de CloudWatch Logs, no incluidos en ninguna comparación de precio publicada.
- La frontera padre/hijo puede erosionarse; se controla con pruebas que fallan si un paso no idempotente aparece en una definición Express.
- El adaptador de Cloud Workflows no reproduce la estructura: la anidación se sustituye por persistir estado, terminar y relanzar.

### Neutras

- El `SagaPort` expone `suspend_until(correlation_id)` en lugar de `wait_for_task_token(timeout)`; el adaptador elige el mecanismo.
- Los payloads entre padre e hijos son punteros a objetos, nunca contenido ([ADR-0011](0011-punteros-a-objetos-en-lugar-de-payloads.md)).

## Criterios de revisión

- **Si las transiciones del padre medidas en producción superan el presupuesto por sesión**, procede revisar la frontera padre/hijo antes que aceptar la factura.
- **Si una ejecución real alcanza el 60 % del límite de 25.000 eventos**, hay que adoptar el patrón documentado de iniciar nuevas ejecuciones.
- **Si AWS elimina la restricción de `.waitForTaskToken` en Express** o amplía su duración máxima, la separación pierde su motivo principal.
- **Si el coste de CloudWatch Logs de los hijos supera el ahorro en transiciones del padre** —con datos propios, no del blog—, la anidación deja de estar justificada.
- **Si el volumen en GCP hace del patrón de relanzamiento el modelo dominante**, conviene evaluar adoptarlo también en AWS por simetría operativa.

## Referencias

- [Step Functions service quotas](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html)
- [Choosing workflow type in Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/choosing-workflow-type.html)
- [Starting new executions to avoid reaching the history quota](https://docs.aws.amazon.com/step-functions/latest/dg/bp-history-limit.html)
- [Building cost-effective AWS Step Functions workflows — AWS Compute Blog](https://aws.amazon.com/blogs/compute/building-cost-effective-aws-step-functions-workflows/)
- [aws-arquitecturas-de-referencia — Ficha 5 y verificación de cifras, puntos 1, 5 y 6](../referencias/aws-arquitecturas-de-referencia.md)
- [Wait using callbacks | Workflows](https://docs.cloud.google.com/workflows/docs/creating-callback-endpoints)
