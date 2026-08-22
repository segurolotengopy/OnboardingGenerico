# Modulo `aws/kms`

## Que crea

- **Llave de plataforma** (`alias/og-{env}-platform`) con rotacion automatica anual, para el cifrado en
  reposo de tablas, buckets compartidos y log groups.
- **Una CMK por tenant** mediante `for_each` sobre `var.tenants`, con alias
  `alias/og-{env}-tenant-<id>` y politica de llave que exige
  `kms:EncryptionContext:tenant = <tenant_id>`.
- **Un grant por tenant** con `EncryptionContextEquals` hacia el rol tenant-scoped, opcional.

## Como se usa

```hcl
module "kms" {
  source = "../../modules/aws/kms"
  env    = var.env

  tenants = {
    "acme"    = { tier = "premium",  jurisdiction = "MX" }
    "globex"  = { tier = "standard", jurisdiction = "PY" }
  }

  deletion_window_in_days    = 30
  tenant_grant_principal_arn = module.identity.tenant_scoped_role_arn
  key_administrator_arns     = [var.security_admin_role_arn]
}
```

Agregar un tenant es agregar una entrada al mapa: `for_each` crea su llave, su alias y su grant sin
tocar los de los demas tenants.

## Advertencias

- **Crypto-shredding, no borrado.** Destruir la CMK del tenant deja ilegible todo su material cifrado,
  incluida la evidencia bajo S3 Object Lock que no puede borrarse fisicamente. Es el unico mecanismo
  que concilia "derecho de supresion" con "retencion WORM obligatoria". Pero la ventana de AWS KMS es
  de **7 a 30 dias con minimo duro de 7**: un SLA de borrado de 72 horas es imposible de cumplir por
  esta via.
- **Coste por llave.** Una CMK cuesta del orden de 1 USD/mes solo por existir, y la rotacion agrega otro
  tanto. Mil tenants con CMK dedicada son miles de dolares al mes antes de la primera operacion
  criptografica. Para tenants no regulados use **branch keys del hierarchical keyring** sobre la tabla
  `keystore` del modulo `aws/data`: mismo aislamiento criptografico, sin coste por llave.
- **No use `CachingCryptoMaterialsManager`.** En entornos concurrentes, cuando expira una entrada de
  cache no hay coordinacion entre hilos y N hilos generan N data keys distintas. Ese es el problema,
  no la solucion. Use el **hierarchical keyring** (recomendacion de AWS) o una cache con carga atomica.
- **`CreateGrant` esta limitada a 50 req/s**, cuota independiente de las operaciones criptograficas.
  Crear grants en caliente durante el onboarding topa a ~50 altas de tenant por segundo. Los grants
  pertenecen al flujo de provisioning.
- **Cuota compartida de operaciones criptograficas:** 100.000 req/s en `us-east-1`, `us-west-2` y
  `eu-west-1`; 20.000 en un segundo grupo de regiones; 10.000 en el resto. Es una cuota **de cuenta**,
  compartida con todo lo demas. Sin cache de data keys, una llamada KMS por operacion convierte esa
  cuota en el techo de throughput del middleware entero.
- **`multi_region` es irreversible**: una llave multi-region no puede volver a ser regional.
- **La sentencia `EnableIamUserPermissions` no es opcional.** Sin ella la llave queda huerfana y no hay
  forma de recuperar el control.
- Cambiar `deletion_window_in_days` no afecta a llaves ya programadas para destruccion.
