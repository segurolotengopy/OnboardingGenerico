# ADR-0001 — Arquitectura hexagonal con núcleo agnóstico, AWS como implementación de referencia y GCP como alternativa

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [02 — Arquitectura](../02-arquitectura.md) · [10 — Multinube AWS y GCP](../10-multicloud-aws-gcp.md) · [05 — Multitenancy](../05-multitenancy-y-aislamiento.md) · [ADR-0005](0005-aislamiento-multitenant-en-capas.md) · [ADR-0009](0009-liveness-mediante-proveedor-certificado-unico.md) |

## Contexto

Onboarding Genérico se interpone entre sistemas requirentes (fintechs, neobancos, banca) y proveedores de verificación de identidad. Su valor está en **componer dinámicamente** los pasos según el tenant, el país y el tipo de documento; no en ejecutar mejor ninguna capacidad concreta.

Hay tres ejes de variabilidad simultáneos y previstos desde el día uno:

1. **Por nube.** Clientes con acuerdos marco distintos exigen AWS o GCP. Es condición de venta, no preferencia técnica.
2. **Por proveedor.** Cada capacidad tiene varios proveedores intercambiables, y el correcto **difiere por país y por tenant**.
3. **Por jurisdicción.** El mismo puerto se invoca con umbrales distintos: la CNBV mexicana exige prueba de vida certificada y detección de ataques de inyección desde el 1 de julio de 2026, mientras ASFI y SEPRELAD no fijan umbral PAD alguno.

La investigación de paridad AWS→GCP documenta **nueve brechas**, tres críticas: no existe liveness gestionado en GCP; no existe equivalente de `dynamodb:LeadingKeys` en ninguna forma; y ambas nubes abandonaron la revisión humana gestionada. Cualquier estrategia multinube debe responder a esas tres o quedará bloqueada al escribir el segundo adaptador.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Time-to-market de la primera versión | Favorece acoplarse a una nube y no pagar la indirección |
| Requisito comercial de desplegar en GCP | Un núcleo acoplado a AWS obliga a reescribir lógica de negocio |
| Brechas de paridad silenciosas | Un puerto mal diseñado produce un adaptador que **funciona pero no aísla** |
| Variabilidad por proveedor y por país | Existe con o sin multinube: el patrón de puertos se necesita igual |
| Coste de dos implementaciones de infraestructura | Cada adaptador tiene mantenimiento, pruebas y SDK que actualizar |
| Servicios gestionados diferenciales | Renunciar a ellos por portabilidad encarece y empeora el producto |

## Opciones consideradas

### Opción A — Acoplamiento directo a AWS

Aplicación escrita contra los SDK de AWS, sin capa de puertos: el dominio manipula `boto3`, la persistencia usa `PK`/`SK` en firmas públicas, la orquestación se expresa en ASL.

**A favor**
- Ruta más rápida a producción y menos código.
- Explota sin fricción lo que no tiene equivalente: `dynamodb:LeadingKeys`, `waitForTaskToken` con horizonte de **1 año**, los beacons de búsqueda del AWS Database Encryption SDK.
- Sin riesgo de abstracción defectuosa que oculte semántica importante.

**En contra**
- Si el requisito de GCP se materializa, la migración es reescritura: el dominio conoce primitivas de DynamoDB sin equivalente en Firestore.
- La variabilidad por proveedor y país sigue existiendo, y sin puertos se implementa con condicionales en el código de integración — el estado del que el producto quiere sacar a sus clientes.
- Impide probar el núcleo sin infraestructura, lo que frena el desarrollo desde el primer mes.

### Opción B — Abstracción total sobre Kubernetes

Sustrato portable en ambas nubes: PostgreSQL, motor de workflows autogestionado, almacenamiento compatible S3, KMS externo.

**A favor**
- Portabilidad verificable, incluida la opción on-premise que algún cliente regulado podría exigir.
- Una sola implementación por componente: sin divergencia de comportamiento entre nubes.
- Elimina las brechas de paridad de servicios gestionados.

**En contra**
- Traslada al equipo la operación de un motor de workflows, una base de datos, un plano de claves y un clúster, con guardias 24×7. Es un desvío enorme para un producto cuyo valor es componer capacidades.
- **No resuelve las brechas que importan**: liveness certificado, cribado AML y registros gubernamentales son servicios externos en cualquier sustrato.
- Pierde controles que un auditor reconoce de inmediato: S3 Object Lock, GCS Bucket Lock, destrucción programada de claves.
- El coste base de un clúster multirregión supera al de un plano serverless con tráfico irregular, que es el perfil real del producto.

### Opción C — Hexagonal con AWS de referencia

Núcleo sin dependencias de nube, comunicándose por **puertos** definidos en términos del dominio, con adaptador AWS, GCP y local. AWS se despliega primero y define el conjunto de pruebas canónico.

**A favor**
- Un solo mecanismo cubre los tres ejes; el de proveedor por país, que es el más activo, se beneficia igual.
- Permite usar los servicios gestionados a fondo dentro del adaptador, sin contaminar el dominio.
- El adaptador local hace el núcleo probable sin credenciales y es la **prueba barata de que el puerto no está acoplado**: si cuesta escribirlo, el puerto está mal diseñado.
- Admite respuesta explícita por brecha: puertos que se portan, puertos cuya forma dicta GCP, y puertos que se construyen a medida en ambas.

**En contra**
- Coste de indirección permanente: más tipos, más traducción, más pruebas.
- **Riesgo real de abstracción con fugas**: si la interfaz se diseña contra la primitiva más potente, el segundo adaptador es inviable o inseguro.
- «AWS de referencia» tiende a degradar en «GCP de segunda», con adaptadores que se escriben tarde y se prueban poco.

## Decisión

**Se adopta la opción C.** El argumento decisivo no es la portabilidad entre nubes —que sola no justificaría el coste— sino que **el mismo mecanismo resuelve los tres ejes**, y el de proveedor por país es inevitable. La multinube resulta un beneficio adicional de una estructura que el dominio necesitaba igualmente.

Se adoptan dos reglas correctoras:

1. **La forma del puerto la dicta el sustrato más restrictivo.** Cuando AWS y GCP divergen, la interfaz se escribe contra GCP y AWS añade refuerzo redundante. Sin esta regla, `TenantIsolationPort` quedaría casi vacío y el adaptador GCP resultaría **estructuralmente inseguro** ([ADR-0005](0005-aislamiento-multitenant-en-capas.md)).
2. **Donde ninguna nube ofrece el servicio en condiciones de uso regulado, se construye a medida en ambas.** Es contraintuitivo, pero **elimina** riesgo de portabilidad: lo que se construye una vez corre igual en las dos ([ADR-0009](0009-liveness-mediante-proveedor-certificado-unico.md), [ADR-0010](0010-revision-humana-construida-a-medida.md)).

El estatus de referencia de AWS es operativo, no arquitectónico: fija el orden de despliegue y las pruebas canónicas, y **no autoriza** que una primitiva de AWS aparezca en una firma de puerto.

## Consecuencias

### Positivas

- El núcleo es ejecutable y probable sin credenciales de nube, con pruebas unitarias en segundos.
- Cambiar de proveedor para un tenant es configuración, no despliegue ([ADR-0007](0007-registro-de-capacidades-dirigido-por-especificacion.md)).
- Los cuatro puertos de riesgo alto quedan acotados: `SagaPort`, `EnvelopeCryptoPort`, `DeterministicIndexPort` y `LivenessPort` si se divergiera.
- Hace visible, y por tanto presupuestable, el trabajo de frontend que implica cambiar de proveedor de liveness.

### Negativas

- Volumen de código mayor: tres implementaciones más una interfaz por capacidad.
- Se renuncia a expresar el dominio en las primitivas más eficientes de DynamoDB.
- El adaptador GCP tiende a rezagarse; el procedimiento de validación de paridad lo mitiga, pero es disciplina recurrente.
- La indirección se paga siempre, incluso para clientes que nunca pedirán GCP.

### Neutras

- El paquete se distribuye con extras por nube (`[aws]`, `[gcp]`, `[cv]`).
- Pruebas de arquitectura automatizadas fallan si un cliente de nube se importa fuera de su adaptador.

## Criterios de revisión

- **Si transcurren dos años sin despliegue productivo en GCP**, el eje de nube deja de estar justificado por demanda y procede simplificar el catálogo de adaptadores, conservando los puertos por los otros dos ejes.
- **Si entra un tercer sustrato** (Azure u on-premise exigido por un regulador), hay que reevaluar la opción B: con tres destinos el cálculo cambia de signo.
- **Si GCP publica un equivalente de `dynamodb:LeadingKeys`**, la regla «la forma la dicta GCP» pierde su justificación principal.
- **Si la deriva entre adaptadores supera el umbral de [10 §8](../10-multicloud-aws-gcp.md) dos trimestres seguidos**, la respuesta es reducir el alcance del adaptador rezagado a lo efectivamente vendido.

## Referencias

- [gcp-paridad-de-servicios §3 — Brechas críticas de paridad](../referencias/gcp-paridad-de-servicios.md)
- [gcp-paridad-de-servicios §4 — Recomendaciones de diseño hexagonal](../referencias/gcp-paridad-de-servicios.md)
- [cumplimiento-normativo-y-estandares §A.2.3 y §F](../referencias/cumplimiento-normativo-y-estandares.md)
- [Firestore Security Rules — las bibliotecas de servidor las eluden](https://firebase.google.com/docs/firestore/security/get-started)
- [Step Functions service quotas](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html)
- [Workflows quotas and limits](https://docs.cloud.google.com/workflows/quotas)
