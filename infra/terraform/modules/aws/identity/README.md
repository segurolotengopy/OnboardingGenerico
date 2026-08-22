# Modulo `aws/identity`

## Que crea

- **Cognito User Pool** con atributo inmutable `custom:tenant_id`, politica de contrasena estricta y
  trigger de **pre token generation V2_0** (unico evento que admite `claimsAndScopeOverrideDetails` y
  por tanto `principal_tags`).
- **Cliente de aplicacion** con secreto, solo flujos SRP y refresh.
- **Proveedor OIDC de IAM** apuntando al emisor del user pool, requisito de `AssumeRoleWithWebIdentity`.
- **Rol tenant-scoped** cuya trust policy permite `sts:AssumeRoleWithWebIdentity` **y** `sts:TagSession`,
  con `aud` fijado al cliente y `sts:TransitiveTagKeys` limitado a `TenantID`.
- **Politicas ABAC**: DynamoDB por `dynamodb:LeadingKeys` (con `Deny` explicito de `Scan`) y S3 por
  prefijo `${aws:PrincipalTag/TenantID}/`, mas uso de KMS condicionado por
  `kms:EncryptionContext:tenant`.
- **Rol de plataforma** opcional para operaciones transversales sin tenant.

## Como se usa

```hcl
module "identity" {
  source     = "../../modules/aws/identity"
  env        = var.env
  aws_region = var.aws_region

  pre_token_generation_lambda_arn = module.compute.function_arns["pre-token-generation"]

  tenant_table_arns   = [module.data.core_table_arn]
  tenant_bucket_arns  = [module.storage.documents_bucket_arn, module.storage.biometrics_bucket_arn]
  tenant_kms_key_arns = values(module.kms.tenant_key_arns)

  mfa_configuration          = "ON"
  enable_deletion_protection = true
}
```

## Advertencias

- **`sts:TagSession` es obligatorio en la trust policy.** Si falta, la federacion sigue funcionando pero
  los principal tags se descartan sin error visible y todas las politicas de datos empiezan a denegar.
  Es el fallo mas comun de este patron.
- **El trigger debe fallar cerrado.** Un usuario sin tenant asignado no debe recibir token. Terraform no
  puede garantizarlo: es logica del codigo de la Lambda. Ver `policies/cognito-pre-token-generation.md`.
- **`dynamodb:LeadingKeys` protege la partition key de la tabla base.** Un **LSI** hereda la proteccion;
  un **GSI no**. Todo GSI debe llevar `TENANT#<tenantId>` como partition key propia, o queda fuera del
  perimetro IAM. Esto colisiona con los beacons del AWS Database Encryption SDK, cuyos GSI usan el
  beacon como PK: la resolucion es construir beacons compuestos que incorporen el tenant como primera
  parte.
- **La clave de condicion es plural y exige `ForAllValues:`** incluso para operaciones de item unico.
- **`Scan` escapa a `LeadingKeys`** porque no declara claves; por eso hay un `Deny` explicito.
- **Presupuesto de session tags:** el maximo por operacion de STS es **50**, con claves de hasta 128
  caracteres y valores de hasta 256. `TenantID` + `tier` + `jurisdiction` + `role` ya consumen cuatro;
  mantenga el conjunto minimo y estable.
- El `encryption context` usado al cifrar debe **coincidir exactamente** con el de los grants de KMS.
  Una discrepancia produce `AccessDeniedException` en el descifrado, no un fallo al cifrar, lo que la
  hace dificil de detectar en pruebas.
- `custom:tenant_id` es inmutable por diseno. Reasignar un usuario a otro tenant obliga a recrearlo.
