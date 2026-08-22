# ADR-0002 — Terraform/OpenTofu como infraestructura como código principal, con módulos separados por nube

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [ADR-0001](0001-arquitectura-hexagonal-multinube.md) · [16 — Despliegue AWS](../16-guia-de-despliegue-aws.md) · [17 — Despliegue GCP](../17-guia-de-despliegue-gcp.md) · [10 — Multinube](../10-multicloud-aws-gcp.md) |

## Contexto

El spec original especificaba **AWS CDK en Python**. Era coherente con un producto exclusivamente AWS, y deja de serlo bajo [ADR-0001](0001-arquitectura-hexagonal-multinube.md): el sistema debe desplegarse en AWS y en GCP con el mismo modelo operativo.

La infraestructura no es homogénea. En AWS: API Gateway, Lambda con imágenes de contenedor, Step Functions Standard y Express, DynamoDB con streams y TTL, S3 con Object Lock, KMS con la tabla de *branch keys*, Secrets Manager, Parameter Store, roles ABAC y VPC con egreso controlado. En GCP: API Gateway, Cloud Run con GPU, Cloud Workflows, Cloud Tasks, Firestore, GCS con Bucket Lock, Cloud KMS, Secret Manager, Workload Identity Federation y VPC Service Controls.

Dos características del dominio pesan más que la ergonomía del lenguaje:

- **Recursos con propiedades irreversibles.** S3 Object Lock en modo *compliance*, la retención de un bucket bloqueado, la longitud de un *beacon* de búsqueda —que **no puede cambiarse tras escribir registros**— y la política de destrucción de claves de KMS. Una herramienta que oculte el diff antes de aplicar es un riesgo de cumplimiento.
- **Auditoría.** Un supervisor puede pedir evidencia de qué configuración estaba vigente en una fecha. El artefacto que se muestra debe ser legible por alguien que no sea desarrollador.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Dos nubes con un modelo operativo único | Descarta herramientas de un solo proveedor |
| Recursos con configuración irreversible | Exige un plan explícito y diferenciable antes de aplicar |
| Auditoría por terceros no desarrolladores | Favorece un artefacto declarativo sobre un programa |
| El equipo y el runtime son Python ([ADR-0003](0003-python-312-como-runtime-principal.md)) | Favorece una herramienta en Python |
| Riesgo de licencia de la herramienta | El cambio de HashiCorp a BUSL en 2023 es precedente directo |
| Matriz de regiones × nubes × entornos | Un DSL declarativo puro puede quedarse corto |

## Opciones consideradas

### Opción A — AWS CDK en Python (lo que pedía el spec original)

Infraestructura como programa Python que sintetiza CloudFormation. Para GCP habría que emparejarlo con otra herramienta o aceptar dos modelos operativos incompatibles.

**A favor**
- Mismo lenguaje que el runtime: un solo ecosistema de tipos, tests y lint, sin cambio de contexto.
- Los *constructs* de nivel 2 y 3 encapsulan buenas prácticas de AWS con muy poco código.
- Composición y pruebas unitarias de infraestructura con las herramientas de un lenguaje real.

**En contra**
- **Es específico de AWS**: obliga a mantener dos herramientas y dos modelos mentales de despliegue.
- Hereda los límites de CloudFormation: cobertura con retraso, *rollback* difícil de razonar y estados de *stack* que requieren intervención manual.
- `cdk diff` muestra el diff del template sintetizado, no del recurso real; con recursos irreversibles esa opacidad es cara.
- El artefacto auditable es un programa: demostrar qué configuración regía exige ejecutar la síntesis.

### Opción B — Pulumi

Infraestructura como programa, con proveedores para ambas nubes y motor de estado propio.

**A favor**
- Única opción que combina multinube **y** lenguaje de programación general.
- Proveedores derivados en buena parte de los de Terraform: cobertura comparable.
- `pulumi preview` da un diff equiparable al `plan`, y el modelo de secretos está integrado.

**En contra**
- El estado gestionado por defecto es un SaaS de terceros. Es autoalojable, pero para datos biométricos de categoría especial la opción por defecto obliga a una revisión de subencargados que las alternativas no requieren.
- Ecosistema de módulos y de conocimiento operativo sensiblemente menor.
- Comparte con CDK la crítica de auditoría: el artefacto revisable es código imperativo.
- Motor y backend dependen de una sola empresa, sin bifurcación establecida.

### Opción C — Terraform/OpenTofu con módulos por nube

HCL declarativo, proveedores oficiales `aws` y `google`, estado remoto con bloqueo y módulos independientes bajo una convención común de nombres y etiquetas.

**A favor**
- **Un modelo operativo único** para las dos nubes y para proveedores externos con proveedor Terraform (DNS, observabilidad, el SaaS de liveness de [ADR-0009](0009-liveness-mediante-proveedor-certificado-unico.md)).
- `plan` produce un diff recurso a recurso con marcado explícito de reemplazo destructivo: el control que exigen los recursos irreversibles.
- HCL es legible por quien no programa, y el artefacto que se audita es el que se aplica.
- Ecosistema mayor: módulos verificados, análisis estático de seguridad (`tfsec`, `checkov`) y estimación de coste integrables en CI sin desarrollo propio.
- **OpenTofu elimina el riesgo de licencia**: bifurcación bajo la Linux Foundation, compatible a nivel de configuración.

**En contra**
- HCL no es un lenguaje de programación: la lógica condicional vive en `count`, `for_each` y ternarios, difíciles de leer a cierta complejidad.
- Cambio de contexto para un equipo de Python.
- El archivo de estado es un activo crítico: valores sensibles, bloqueo, cifrado, control de acceso, y su divergencia es un modo de fallo real.
- No hay reutilización real entre los módulos de AWS y los de GCP: dos árboles paralelos que comparten convención, no implementación.

## Decisión

**Se adopta la opción C. Se abandona AWS CDK en Python del spec original.**

El argumento decisivo es la combinación de **modelo operativo único** y **legibilidad del plan antes de aplicar**. La segunda cierra la discusión: en un sistema que fija retención WORM, destrucción de claves y parámetros criptográficos irreversibles, poder revisar exactamente qué se va a cambiar —en un formato que entiende un oficial de cumplimiento— pesa más que compartir lenguaje con la aplicación.

La ventaja de la opción A es real pero **local**: acelera la escritura y no aporta nada en revisión ni en auditoría, que es donde este proyecto gasta más tiempo por recurso. Pulumi era la alternativa más seria y se descarta por el modelo de estado por defecto y el tamaño del ecosistema, no por deficiencia técnica.

**No se adopta un módulo común sobre ambas nubes.** La abstracción multinube vive en los puertos de la aplicación; un módulo Terraform «agnóstico» produciría la peor versión de los dos mundos.

## Consecuencias

### Positivas

- El mismo flujo —`fmt`, `validate`, `plan`, revisión, `apply`— sirve para AWS, GCP y proveedores externos.
- `plan` en el pull request convierte el cambio de infraestructura en artefacto revisable, con los reemplazos destructivos visibles antes de aprobar.
- Análisis estático de seguridad y cumplimiento con herramientas de terceros.
- OpenTofu da salida ante un cambio de licencia sin migrar configuración.

### Negativas

- Dos árboles de módulos que pueden divergir; la convención `og-{env}-{componente}` y las etiquetas obligatorias son disciplina, no garantía.
- Un lenguaje más que mantener además del de la aplicación.
- El estado remoto pasa a ser componente crítico con requisitos propios de cifrado, bloqueo y respaldo.
- Recursos en vista previa pueden exigir llamadas a la API fuera de Terraform hasta que el proveedor los cubra.

### Neutras

- OpenTofu es la implementación de referencia en CI; los módulos se mantienen compatibles con Terraform.
- La convención de nombres y las etiquetas obligatorias (`project`, `env`, `owner`, `data-classification`, `cost-center`) se validan por política estática.

## Criterios de revisión

- **Si OpenTofu y Terraform divergen** hasta que una configuración deje de aplicar en ambos, hay que elegir uno y documentarlo.
- **Si la divergencia entre módulos de nube se vuelve fuente recurrente de incidentes**, procede evaluar un generador de configuración común sobre los proveedores existentes.
- **Si el proveedor oficial de una nube deja sin cubrir un recurso obligatorio más de dos trimestres**, hay que reevaluar la herramienta para esa nube.
- **Si un módulo exige de forma reiterada lógica que HCL no expresa con claridad**, la variabilidad debe resolverse con generación de configuración, no con más `for_each`.

## Referencias

- [Terraform — AWS provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs) · [Google provider](https://registry.terraform.io/providers/hashicorp/google/latest/docs)
- [OpenTofu](https://opentofu.org/)
- [AWS Database Encryption SDK — Choosing a beacon length](https://docs.aws.amazon.com/database-encryption-sdk/latest/devguide/choosing-beacon-length.html)
- [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html) · [GCS Bucket Lock](https://cloud.google.com/storage/docs/bucket-lock)
- [CLAUDE.md — reglas estructurales del repositorio](../../CLAUDE.md)
