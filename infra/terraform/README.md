# Infraestructura como codigo — Onboarding Generico

Terraform (compatible con OpenTofu) para el middleware serverless multi-tenant de onboarding y eKYC.
**AWS es la implementacion de referencia; GCP es la alternativa.** Los dos arboles de modulos son
independientes y se activan con la variable `cloud_provider`.

---

## Estructura

```
infra/terraform/
├── versions.tf          Versiones de referencia de Terraform y de los providers
├── modules/aws/         10 modulos: networking, identity, data, storage, kms,
│                        orchestration, compute, api, observability, gdpr
├── modules/gcp/         Los mismos 10 modulos, adaptados a GCP
├── envs/{dev,stg,prd}/  Modulos raiz por entorno
└── policies/            Politicas IAM de referencia y el trigger de Cognito
```

Cada modulo tiene `main.tf`, `variables.tf`, `outputs.tf` y un `README.md` con una seccion de
**Advertencias** que documenta los limites reales y las trampas conocidas. **Leala antes de usar el
modulo**: varias decisiones de este arbol son irreversibles.

Los modulos **no** declaran su propio bloque `required_providers`: heredan la configuracion del modulo
raiz. Las versiones probadas estan en `versions.tf` y replicadas en cada entorno.

---

## Prerrequisitos

| Herramienta | Version |
|---|---|
| Terraform | >= 1.6 |
| OpenTofu | >= 1.6 (alternativa; el codigo no usa funciones exclusivas de ninguna) |
| Provider AWS | ~> 5.60 |
| Provider Google y Google Beta | ~> 6.10 |

**Credenciales.** Nunca claves de acceso permanentes. En AWS, un rol asumido desde el pipeline con
OIDC; en GCP, Workload Identity Federation desde el sistema de integracion continua.

**Fuera de este arbol** (bootstrap separado, porque no puede depender de si mismo):

- Bucket de estado de Terraform (S3 o Cloud Storage) con versionado y cifrado.
- Bucket de artefactos con los `.zip` de las funciones Lambda, que produce el pipeline de construccion.
- Aceptacion del acuerdo de Marketplace para habilitar los modelos de Claude en Model Garden si se
  despliega GCP: **no existe recurso de Terraform que lo haga**, es un paso manual del runbook.

---

## Como elegir la nube

La variable `cloud_provider` de cada entorno acepta `aws`, `gcp` o `both`. Los modulos se activan con
`count`, de modo que un `plan` con `cloud_provider = "aws"` ni siquiera evalua el arbol de GCP.

```hcl
cloud_provider = "aws"  # implementacion de referencia
cloud_provider = "gcp"  # alternativa
cloud_provider = "both" # ambas, para pruebas de portabilidad
```

`both` no es un modo de produccion: sirve para validar que el nucleo hexagonal funciona contra los dos
conjuntos de adaptadores. Desplegar los dos arboles en produccion duplica el perimetro de datos y las
obligaciones de cumplimiento.

---

## Orden de aplicacion

Terraform resuelve el grafo de dependencias por si mismo: **basta con un `apply` del entorno**. Este
orden importa cuando hay que aplicar por objetivos tras un fallo parcial, o al construir un entorno
nuevo por fases.

| # | AWS | GCP |
|---|---|---|
| 1 | `kms` | `identity` (cuentas de servicio) |
| 2 | `networking` | `kms` |
| 3 | `data`, `storage` | `networking` |
| 4 | `identity` | `data`, `storage` |
| 5 | `compute` | `compute` |
| 6 | `observability` (crea el bus de eventos) | `orchestration` |
| 7 | `orchestration` | `api` |
| 8 | `api` | `observability` |
| 9 | `gdpr` | `gdpr` |

Dos dependencias circulares aparentes se rompen en el modulo raiz construyendo el identificador a mano:

- **AWS**: `observability` vigila la maquina de estado que `orchestration` crea, y `orchestration`
  publica en el bus que `observability` crea. El ARN de la maquina de estado se construye en `locals`.
- **GCP**: `identity` necesita los nombres de bucket y `storage` necesita la cuenta de servicio de
  `identity`. Los nombres de bucket se construyen en `locals`.

```bash
cd envs/dev
cp backend.tf.example backend.tf          # y sustituya los marcadores
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

---

## Backends remotos

Los archivos `backend.tf.example` de cada entorno traen los dos bloques con marcadores. **Un directorio
de Terraform tiene un solo backend**, aunque despliegue en dos nubes.

| Nube | Backend | Bloqueo |
|---|---|---|
| AWS | `s3` | `use_lockfile = true` (nativo de S3) o una tabla de DynamoDB |
| GCP | `gcs` | Nativo, sin recurso adicional |

El estado contiene valores sensibles: secretos de cliente de Cognito, valores de claves de API. El
bucket debe estar cifrado, versionado, con acceso publico bloqueado y con lectura auditada. En
produccion, en una cuenta o proyecto **distinto** del entorno.

---

## Diferencias entre entornos

| Aspecto | dev | stg | prd |
|---|---|---|---|
| Retencion de logs | 7 dias | 90 dias | 400 dias |
| PITR / recuperacion a un punto en el tiempo | no | si | si |
| Proteccion de borrado (servicio) | no | si | si |
| `prevent_destroy` en datos y llaves | no | no | **si** |
| Modo de Object Lock | GOVERNANCE | GOVERNANCE | **COMPLIANCE** |
| Bucket Lock de Cloud Storage bloqueado | no | no | **si** |
| `min_instances` de Cloud Run | 0 | 1 | 2 |
| Concurrencia aprovisionada de Lambda | 0 | 0 | > 0 en el camino critico |
| Endpoints de tipo Interface / PSC | no | si | si |
| WAF | no | si | si |
| `include_execution_data` en Step Functions | si | no | **no** |
| Ventana de destruccion de llaves | 7 dias / 1 dia | 14 dias | 30 dias |
| MFA en Cognito | OPTIONAL | ON | ON + seguridad avanzada ENFORCED |

En `prd`, las variables con consecuencias irreversibles o regulatorias (`document_retention_days`,
`biometric_retention_days`, `evidence_retention_years`, `key_administrator_arns`) **no tienen valor por
defecto**: hay que declararlas de forma explicita para que la decision quede registrada en el control
de versiones.

---

## Etiquetas obligatorias

Cinco etiquetas en todos los recursos: `project`, `env`, `owner`, `data-classification`, `cost-center`.

- **AWS**: con `default_tags` en el provider. Los modulos solo agregan las especificas del recurso
  (`data-classification` real de cada bucket o tabla, `tenant-id` en las llaves).
- **GCP**: con `default_labels` en el provider. Las etiquetas de GCP solo admiten minusculas, digitos,
  guiones y guiones bajos, por lo que `data-classification` se escribe `data_classification`.

---

## Lo que hay que leer antes de tocar produccion

Cinco decisiones de este arbol son **irreversibles**. Estan documentadas en el README del modulo
correspondiente:

1. **Object Lock solo se habilita al crear el bucket** (`modules/aws/storage`). Y el modo **COMPLIANCE
   no lo puede eludir nadie, ni el root de la cuenta**.
2. **El Bucket Lock de Cloud Storage, una vez bloqueado, solo puede alargarse** (`modules/gcp/storage`).
3. **`PK = TENANT#<tenantId>` no es retrofitable** sin migracion completa de datos
   (`modules/aws/data`), porque `dynamodb:LeadingKeys` depende de ese prefijo.
4. **La longitud de beacon del AWS Database Encryption SDK no puede cambiarse** una vez escritos
   registros, y los beacons no se calculan retroactivamente (`modules/aws/data`).
5. **Los keyrings y las llaves de Cloud KMS no se pueden borrar nunca** (`modules/gcp/kms`).

Y una diferencia silenciosa que cuesta cara: **el borrado suave de Cloud Storage esta activo por
defecto y retiene los objetos 7 dias**, lo que hace que un `Delete` no sea un borrado. El modulo
`gcp/storage` lo desactiva de forma explicita. S3 no tiene ese comportamiento.

---

## Politicas de referencia

`policies/` contiene el material que hay que entender para que el aislamiento multi-tenant funcione:

| Archivo | Contenido |
|---|---|
| `tenant-abac-dynamodb.json` | `dynamodb:LeadingKeys` con `${aws:PrincipalTag/TenantID}`, `Deny` de `Scan` y lectura del Registro de Capacidades |
| `tenant-abac-s3.json` | Scoping por prefijo de objeto, `s3:prefix` en `ListBucket`, uso de KMS por encryption context |
| `kms-key-policy-tenant.json` | Politica de llave por tenant con `Deny` de destruccion fuera del rol de operaciones |
| `cognito-pre-token-generation.md` | El trigger V2.0 que inyecta `principal_tags`, la trust policy con `sts:TagSession`, y las pruebas que demuestran que la frontera funciona |

Estos archivos son **documentacion canonica**. Las politicas que se aplican de verdad se generan en
`modules/aws/identity` con `data "aws_iam_policy_document"`, para que los ARN salgan de los recursos y
no de cadenas cableadas. Si edita una, edite tambien la otra.

---

## La brecha que no se puede cerrar

**GCP no tiene equivalente a `dynamodb:LeadingKeys`.** Las condiciones de IAM no exponen ningun
atributo de clave de fila o identificador de documento, y las Security Rules de Firestore no protegen a
un backend porque las bibliotecas de cliente de servidor las omiten.

En AWS, el aislamiento lo aplica la plataforma y un error de codigo no lo puede saltar. En GCP, la
barrera es el codigo. Por eso este repositorio compensa en cuatro capas —cifrado de sobre por tenant
con `tenant_id` como Associated Data (el control **primario**), base de datos dedicada por tenant
premium, VPC Service Controls y Data Access audit logs— y por eso el puerto de aislamiento del nucleo
hexagonal **se disena asumiendo el modelo de GCP**, dejando que AWS lo refuerce. Al reves, el adaptador
de GCP queda estructuralmente inseguro.

El detalle esta en `modules/gcp/identity/README.md` y `modules/gcp/data/README.md`.

---

## Pendiente de verificar

Puntos que no se pudieron confirmar contra documentacion oficial y que estan marcados en el codigo:

- **Minimo configurable de `destroy_scheduled_duration` en Cloud KMS.** Se cita habitualmente 24 horas,
  pero la pagina de destruccion y restauracion no lo indica. Verifiquelo antes de comprometer un SLA de
  borrado (`modules/gcp/kms`).
- **Maximo del tiempo de espera de `events.await_callback` en Cloud Workflows** por encima de las 12
  horas por defecto. El parametro es configurable pero no hay techo documentado
  (`modules/gcp/orchestration`).
- **Inconsistencia documental en Cloud Run**: el maximo de memoria por instancia es 32 GiB, pero la GPU
  RTX PRO 6000 Blackwell exige 80 GiB minimos (`modules/gcp/compute`).
- **Cuotas por consumidor en GCP API Gateway**: no consta un recurso de Terraform que las configure, ni
  esta documentado el timeout de peticion del servicio (`modules/gcp/api`).

---

## Convenciones

- Nomenclatura: `og-{env}-{componente}` en las dos nubes.
- Identificadores en ingles; comentarios y descripciones en espanol latinoamericano.
- Indentacion de dos espacios y `=` alineados dentro de cada bloque. Ejecute `terraform fmt -recursive`
  antes de cada commit.
- Ningun valor real ni secreto en el repositorio: `terraform.tfvars` no se versiona y los secretos
  viven en Secrets Manager o Secret Manager, referenciados por nombre y con **version fija**.
- Ningun dato binario viaja por el estado del orquestador: siempre punteros `s3://` o `gs://`.
