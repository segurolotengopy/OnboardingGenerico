# ADR-0005 — Aislamiento multi-tenant en capas, con el cifrado por tenant como control primario portable

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [05 — Multitenancy y aislamiento](../05-multitenancy-y-aislamiento.md) · [06 — Criptografía y gestión de claves](../06-criptografia-y-gestion-de-claves.md) · [ADR-0001](0001-arquitectura-hexagonal-multinube.md) · [ADR-0006](0006-hierarchical-keyring-en-lugar-de-cachingcryptomaterialsmanager.md) · [10 — Multinube](../10-multicloud-aws-gcp.md) |

## Contexto

El middleware almacena, por tenant, expedientes con datos biométricos y documentales que el GDPR clasifica como **categoría especial** (art. 9) y que la Ley 7593/2025 paraguaya declara expresamente dato sensible. Una fuga entre tenants es una brecha notificable en 72 horas y, para el cliente financiero, un incidente ante su supervisor.

En AWS existe un control de plataforma que hace el trabajo pesado: **ABAC con `dynamodb:LeadingKeys`**. Una etiqueta de sesión `TenantID`, inyectada por el *pre-token hook* del proveedor de identidad y propagada mediante `sts:AssumeRoleWithWebIdentity` + `sts:TagSession`, se compara contra la clave de partición del ítem. Si el código pide un ítem de otro tenant, **DynamoDB deniega**: no filtra el código, filtra el motor de datos.

**En GCP no existe equivalente en ninguna forma.** IAM Conditions no expone atributos de clave de fila o documento, y las Security Rules de Firestore son irrelevantes para un backend porque *«the server client libraries bypass all Firestore Security Rules»*. La investigación de paridad la clasifica como la brecha más peligrosa **precisamente porque es silenciosa**: el código funciona, simplemente no está aislado.

De ahí el problema central: si `TenantIsolationPort` se diseña asumiendo el modelo AWS —donde la plataforma aplica la política y el puerto queda casi vacío—, el adaptador GCP no queda *incompleto*, queda **estructuralmente inseguro**, y lo estará sin que ninguna prueba funcional lo detecte.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| `dynamodb:LeadingKeys` es fuerte y barato en AWS | Tentación de convertirlo en la base del diseño |
| GCP no tiene equivalente | Un diseño basado en la plataforma no se porta; el fallo es silencioso |
| Un filtro `WHERE tenant_id` es un solo punto de fallo | Un `if` olvidado o una consulta administrativa lo anulan |
| Datos de categoría especial | El nivel de garantía exigible supera al de un SaaS genérico |
| Infraestructura dedicada es cara | No escala a tenants pequeños; sí a clientes de alto valor |
| El cifrado por tenant añade latencia y coste | Requiere caché de material criptográfico, con su propio riesgo |

## Opciones consideradas

### Opción A — Aislamiento por plataforma en AWS, replicado «lo mejor posible» en GCP

Diseñar contra `dynamodb:LeadingKeys` y aproximarlo en GCP con roles por tenant y filtrado en aplicación.

**A favor**
- Aprovecha al máximo la primitiva más fuerte de la nube de referencia, con muy poco código propio.
- La política ABAC es declarativa y auditable: un revisor la lee en el módulo de Terraform.
- Es el patrón que documenta la guía de arquitectura SaaS de AWS y que un auditor reconoce de inmediato.

**En contra**
- **Descalificador: invierte el riesgo hacia el sustrato débil.** El puerto queda casi vacío porque en AWS no hace falta lógica; el adaptador GCP hereda esa interfaz y no tiene dónde poner la comprobación.
- El fallo resultante es silencioso: pruebas verdes, funcionalidad correcta, aislamiento inexistente.
- Genera una asimetría de garantías entre nubes que hay que explicar en cada DPIA y en cada cuestionario de cliente.

### Opción B — Infraestructura dedicada por tenant en ambas nubes

Un proyecto GCP o una cuenta AWS por tenant, con base de datos, claves y buckets propios.

**A favor**
- El aislamiento más fuerte que existe: sin superficie compartida en el plano de datos.
- Simplifica la argumentación regulatoria ante clientes con exigencias de segregación estricta.
- Facilita la residencia por tenant y el borrado por destrucción de proyecto.

**En contra**
- Coste base incompatible con clientes pequeños y medianos, que son la mayoría del mercado objetivo.
- Firestore admite un tope de **100 bases de datos** por proyecto, lo que acota la variante «base por tenant» y empuja al proyecto por tenant, aún más caro.
- Multiplica despliegues, rotación de claves, parcheo y observabilidad.
- No resuelve el punto donde suele producirse la fuga —un contexto mal propagado en la aplicación— si un mismo proceso sirve a varios tenants.

### Opción C — Filtro en aplicación con revisión y pruebas

Un único repositorio con alcance de tenant, comprobaciones en el código y pruebas de aislamiento.

**A favor**
- Portable por construcción: idéntico en las dos nubes.
- Coste marginal nulo y sin latencia añadida.
- Se adapta a consultas complejas sin pelear con la política de la plataforma.

**En contra**
- **Es un único punto de fallo.** Una consulta administrativa, un endpoint de exportación o un trabajo de migración lo anulan por completo.
- La revisión y las pruebas reducen la probabilidad, no la consecuencia: cuando falla, la fuga es total y no deja rastro distinguible de una operación legítima.
- Ningún auditor lo acepta como control único para datos de categoría especial.

### Opción D — Defensa en capas con el cifrado por tenant como control primario

Cuatro capas: **identidad** (el hook falla cerrado —sin tenant asignado **no se emite token**— e inyecta `tenant_id` y la etiqueta `TenantID`); **aplicación** (repositorio único con alcance de tenant y `TenantContext` explícito, nunca por hilo); **criptografía** (cifrado de sobre por tenant con `tenant_id` como *associated data*); y **plataforma** (`LeadingKeys` en AWS; WIF con `attribute.tenant`, VPC Service Controls y *Data Access audit logs* con alerta de desalineación en GCP).

**A favor**
- **El control primario es portable y produce fallo seguro**: si el alcance se equivoca, la clave del tenant A no descifra el registro del tenant B. El resultado es un **error de descifrado**, no una fuga.
- El fallo es **detectable y alertable**: `crypto.decrypt_failures_by_context` mayor que cero es incidente de seguridad, no ruido.
- Cada capa cubre el modo de fallo de las otras: identidad cubre credenciales mal emitidas, plataforma cubre bugs de aplicación en AWS, criptografía los cubre en ambas nubes.
- Compatible con ofrecer infraestructura dedicada como *tier* superior sin imponer su coste a todos.

**En contra**
- Añade latencia y coste de KMS, que obligan a caché de material criptográfico y a resolver el *cache stampede*.
- Buscar por igualdad sobre un campo cifrado exige un índice determinista aparte, con análisis de fuga de frecuencia propio.
- El *crypto-shredding* queda sujeto a los plazos de destrucción de la nube; en Cloud KMS no es inmediato (30 días por defecto, configurable) y **el mínimo configurable no está verificado**.
- Más piezas: material por tenant, rotación, jerarquía, caché.

## Decisión

**Se adopta la opción D**, y se adopta explícitamente la **inversión de la dirección del diseño**: la forma de `TenantIsolationPort`, `SessionRepositoryPort` y `AuthorizationPort` **la dicta GCP**.

Si AWS dictara la forma, el puerto sería casi vacío —una etiqueta de sesión y una política declarativa— y al portarlo a GCP el adaptador quedaría sin lugar donde comprobar. Escribiéndolo contra el sustrato restrictivo, el puerto **contiene lógica real de alcance** que funciona en las dos nubes y AWS añade `LeadingKeys` como segunda barrera: un solo mecanismo, garantía uniforme, y AWS mejor protegido que GCP en lugar de GCP peor que AWS.

Se rechaza `dynamodb:LeadingKeys` como control *primario* justamente por ser bueno: su calidad induce a apoyarse en él, y esa dependencia rompe la portabilidad de forma silenciosa.

El `RepositoryPort` expone **operaciones de dominio** —`find_by_tenant_and_state`, `append_step_result`— y nunca primitivas `PK`/`SK`/`begins_with`. Un puerto que acepte `begins_with` ya está acoplado a DynamoDB y hace inviable el adaptador de Firestore.

Se conserva la infraestructura dedicada como **tier comercial**, no como modelo por defecto.

## Consecuencias

### Positivas

- Un error de alcance produce fallo de descifrado, no fuga, en **ambas** nubes.
- La métrica de fallos de descifrado por contexto funciona como detector de bugs de aislamiento.
- AWS queda con dos barreras independientes; GCP, con una barrera fuerte más perímetro y auditoría.
- El argumento ante un auditor es el mismo en las dos nubes, lo que simplifica DPIA y cuestionarios.
- El *crypto-shredding* por tenant queda disponible como mecanismo de borrado.

### Negativas

- Latencia y coste de KMS por operación, que hacen obligatoria la caché ([ADR-0006](0006-hierarchical-keyring-en-lugar-de-cachingcryptomaterialsmanager.md)).
- Las consultas de igualdad sobre campos cifrados requieren `DeterministicIndexPort` con HMAC por tenant y análisis de fuga propio.
- La longitud del beacon es **irreversible una vez escritos registros**: un parámetro de dimensionado se convierte en decisión de arquitectura.
- El material por tenant añade estados (activa, rotando, programada para destrucción) que hay que operar y observar.

### Neutras

- El conjunto de etiquetas de sesión se mantiene mínimo y estable —`TenantID`, `Tier`, `Jurisdiction`, `Role`—; el resto del contexto vive en el núcleo, porque las etiquetas son un contrato con IAM.
- Pruebas de arquitectura fallan si el cliente de Firestore o de DynamoDB se importa fuera de su adaptador.

## Criterios de revisión

- **Si GCP publica una condición IAM sobre la clave del documento en Firestore**, la asimetría desaparece y procede reevaluar la forma del puerto.
- **Si el coste o la latencia del cifrado por tenant hacen inviable un segmento de alto volumen**, hay que revisar la jerarquía de claves antes que relajar el control.
- **Si `crypto.decrypt_failures_by_context` supera cero en producción**, se investiga como posible error de alcance, no como fallo criptográfico.
- **Si el mínimo configurable de `destroy_scheduled_duration` en Cloud KMS resulta incompatible con un SLA de borrado** —dato hoy **no verificado**—, hay que rediseñar el *crypto-shredding* en GCP.
- **Si los tenants con base de datos dedicada se aproximan al tope de 100 por proyecto en Firestore**, hay que decidir entre proyecto por tenant o consolidación antes de llegar al límite.

## Referencias

- [gcp-paridad-de-servicios §3, brecha 2 — aislamiento multi-tenant en el plano de datos](../referencias/gcp-paridad-de-servicios.md)
- [gcp-paridad-de-servicios §4 — recomendaciones de diseño hexagonal, punto 4](../referencias/gcp-paridad-de-servicios.md)
- [aws-arquitecturas-de-referencia — Ficha 1, ABAC y STS session tags](../referencias/aws-arquitecturas-de-referencia.md)
- [IAM condition keys for DynamoDB — `dynamodb:LeadingKeys`](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/specifying-conditions.html)
- [Firestore Security Rules — las bibliotecas de servidor las eluden](https://firebase.google.com/docs/firestore/security/get-started)
- [Firestore quotas and limits](https://docs.cloud.google.com/firestore/native/docs/quotas)
- [cumplimiento-normativo-y-estandares §B.6.1 y §B.9.1](../referencias/cumplimiento-normativo-y-estandares.md)
