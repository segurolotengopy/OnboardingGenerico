# Modulo `aws/storage`

## Que crea

| Bucket | Clasificacion | Caracteristicas |
|---|---|---|
| `og-{env}-documents-{sufijo}` | restricted | Versionado, SSE-KMS, transiciones a IA / Glacier IR / Deep Archive |
| `og-{env}-biometrics-{sufijo}` | restricted | Versionado, SSE-KMS, retencion mas corta que documentos |
| `og-{env}-staging-{sufijo}` | internal | Sin versionado, expiracion a 7 dias |
| `og-{env}-evidence-{sufijo}` | restricted | **Object Lock WORM**, versionado obligatorio, sin regla de expiracion |

Todos llevan bloqueo total de acceso publico, `BucketOwnerEnforced` (ACL desactivadas),
`bucket_key_enabled` y una politica que deniega transporte inseguro, subidas sin SSE-KMS y subidas con
una llave KMS distinta a la configurada.

## Como se usa

```hcl
module "storage" {
  source      = "../../modules/aws/storage"
  env         = var.env
  kms_key_arn = module.kms.platform_key_arn

  evidence_object_lock_mode = "COMPLIANCE" # solo en prd
  evidence_retention_years  = 7
  document_retention_days   = 2555
}
```

Convencion de claves obligatoria: `<tenantId>/<caseId>/<tipo>/<objeto>`. El primer segmento **debe**
ser el tenant, porque la politica ABAC restringe por prefijo `${aws:PrincipalTag/TenantID}/`.

## Advertencias

- 🔴 **Object Lock solo puede habilitarse al crear el bucket** y exige versionado. No existe forma de
  activarlo despues: habria que crear un bucket nuevo y copiar los objetos. Si duda entre activarlo o
  no, activelo: un bucket con Object Lock habilitado pero sin retencion por defecto se comporta como
  uno normal.
- 🔴 **Modo COMPLIANCE es irreversible por objeto.** Ni el root de la cuenta puede borrar un objeto
  retenido antes de que expire su retencion. Un error de configuracion (retencion de 100 anios) es
  permanente y se factura hasta el final. GOVERNANCE permite eludir la retencion con
  `s3:BypassGovernanceRetention` y es el valor por defecto por esa razon.
- **Las reglas de ciclo de vida no pueden borrar objetos retenidos por Object Lock.** Por eso el bucket
  de evidencia no lleva regla de expiracion: la unica forma de hacer ilegible esa evidencia antes de
  tiempo es el **crypto-shredding** de la CMK del tenant (modulo `aws/kms`).
- **`force_destroy` nunca se aplica al bucket de evidencia**, ni siquiera en `dev`. Un
  `terraform destroy` de un entorno con evidencia retenida fallara, y eso es lo correcto.
- Las transiciones de ciclo de vida tienen **duracion minima de facturacion por clase** (30 dias en
  Standard-IA, 90 en Glacier IR, 180 en Deep Archive). Transicionar antes de tiempo cuesta mas que no
  transicionar. Ademas hay un cargo por peticion de transicion: para objetos muy pequenos y muy
  numerosos, la transicion puede salir mas cara que el ahorro.
- **La aplicacion de las reglas es asincrona** y puede ir horas por detras del cumplimiento de la
  condicion. No es un temporizador exacto.
- El versionado hace que un `DeleteObject` cree un delete marker, no un borrado. Para el derecho de
  supresion hay que borrar **todas las versiones**; de eso se encarga el modulo `aws/gdpr`.
- `bucket_key_enabled` reduce mucho las llamadas a KMS, pero implica que una sola data key de bucket
  cifra multiples objetos durante un intervalo. Es compatible con el cifrado por tenant a nivel de
  aplicacion, que sigue siendo la barrera real de aislamiento.
