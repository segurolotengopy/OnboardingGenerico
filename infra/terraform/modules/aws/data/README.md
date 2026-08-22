# Modulo `aws/data`

## Que crea

| Tabla | Claves | Proposito |
|---|---|---|
| `og-{env}-core` | `PK = TENANT#<t>`, `SK = CASE#<c>...` | Single-table del dominio, con 3 GSI, TTL, Streams y PITR |
| `og-{env}-capability-registry` | `PK = CAPABILITY#<id>`, `SK = COUNTRY#..#DOCTYPE#..#V<n>` | Registro de Capacidades: que proveedor cubre que paso, pais y tipo de documento |
| `og-{env}-locks` | `PK = LOCK#<tenant>#<recurso>` | Mutex distribuido con TTL y fencing token |
| `og-{env}-keystore` | `PK = branch-key-id`, `SK = version` | Branch keys del hierarchical keyring (AWS Database Encryption SDK) |

## Como se usa

```hcl
module "data" {
  source      = "../../modules/aws/data"
  env         = var.env
  kms_key_arn = module.kms.platform_key_arn

  enable_point_in_time_recovery = true
  enable_deletion_protection    = true
  protect_from_destroy          = true # solo en prd
}
```

## Advertencias

- **`PK = TENANT#<tenantId>` se fija el dia uno.** `dynamodb:LeadingKeys` no es retrofitable sin
  migracion completa de datos.
- **`LeadingKeys` no cubre los GSI.** Los indices globales de este modulo llevan el tenant en su propia
  partition key precisamente por eso. Si agrega un GSI, verifique que su PK empiece por `TENANT#`.
- **El GSI de beacon del AWS Database Encryption SDK es el punto de friccion.** La libreria nombra los
  atributos con prefijo `aws_dbe_b_` y por defecto usa el beacon como PK del indice, lo que lo saca del
  perimetro ABAC. Se resuelve con un **beacon compuesto** cuya primera parte sea el tenant. Ademas:
  la **longitud de beacon se mide en bits** y **no puede cambiarse una vez escritos registros**, y los
  beacons **no se calculan retroactivamente**. Dimensionarlos es una decision irreversible de dia cero.
- **El TTL de DynamoDB no es un mecanismo de borrado garantizado.** El borrado real puede tardar hasta
  48 horas y los items expirados siguen apareciendo en consultas hasta que se eliminan. No sirve para
  cumplir un derecho de supresion; para eso esta el modulo `aws/gdpr`.
- **Los items de caso no deben llevar `expires_at`.** La retencion KYC/AML se mide en anios (5 a 10
  segun jurisdiccion). El TTL es solo para artefactos intermedios.
- **Nunca codifique PII en `PK` o `SK`.** El AWS Database Encryption SDK obliga a `SIGN_ONLY` en las
  claves: viajan en claro. `SK = DOC#<numero_documento>` seria una fuga permanente.
- **Limite de 400 KB por item.** Imagenes, respuestas de OCR completas y payloads de proveedor van a
  S3; la tabla guarda solo el puntero `s3://`.
- **`protect_from_destroy` cambia que recurso existe en el estado.** Alternar el valor sobre una tabla
  con datos provoca destruccion y recreacion. Fijelo al crear el entorno y no lo toque; si necesita
  cambiarlo, use `terraform state mv` entre `aws_dynamodb_table.core[0]` y
  `aws_dynamodb_table.core_protected[0]`.
- El Registro de Capacidades **no lleva prefijo de tenant** porque es catalogo de plataforma. No lo
  incluya en `tenant_table_arns` del modulo de identidad: la politica con `LeadingKeys` lo bloquearia
  por completo.
- Con `parallelization_factor` alto sobre el stream, recuerde que DynamoDB Streams ordena **por clave de
  particion**: un tenant muy activo serializa el avance de sus propios eventos.
