# Modulo `gcp/storage`

## Que crea

| Bucket | Clasificacion | Caracteristicas |
|---|---|---|
| `og-{env}-documents-{sufijo}` | restricted | Versionado, CMEK, transiciones Nearline / Coldline / Archive |
| `og-{env}-biometrics-{sufijo}` | restricted | Versionado, CMEK, retencion mas corta |
| `og-{env}-staging-{sufijo}` | internal | Sin versionado, expiracion a 7 dias |
| `og-{env}-evidence-{sufijo}` | restricted | **Retention policy (Bucket Lock)**, versionado, transicion a Archive |

Todos con `uniform_bucket_level_access`, `public_access_prevention = enforced` y **soft delete
desactivado**.

## Advertencias

- 🔴 **El borrado suave esta activo por defecto en Cloud Storage y retiene los objetos 7 dias.** Eso
  significa que un `Delete` **no es un borrado**, lo cual es incompatible con el derecho de supresion.
  Este modulo lo desactiva de forma explicita (`soft_delete_retention_seconds = 0`). **S3 no tiene este
  comportamiento por defecto**: es una diferencia que se pasa por alto al portar y produce un
  incumplimiento silencioso.
- 🔴 **`is_locked = true` es irreversible.** Una politica de retencion bloqueada solo puede **alargarse**,
  nunca acortarse ni eliminarse, y el bucket no puede borrarse hasta que expire la retencion de todos
  sus objetos. Un error de configuracion es permanente y se factura hasta el final.
- **La retention policy de bucket aplica a todos los objetos por igual.** El equivalente a la retencion
  por objeto de S3 es Object Retention Lock, que es un mecanismo distinto y no se usa aqui.
- **Duraciones minimas de facturacion por clase:** Nearline **30 dias**, Coldline **90 dias**, Archive
  **365 dias**. Transicionar antes cuesta mas que no transicionar.
- **`SetStorageClass` actualiza la fecha de modificacion del objeto** y cuenta como operacion de Clase A
  (con coste). Eso puede reiniciar reglas basadas en `age` mal escritas.
- **Los cambios de configuracion de ciclo de vida tardan hasta 24 horas en surtir efecto** y la
  ejecucion es asincrona. No es un temporizador exacto. Identico a S3.
- 🟢 **Archive de GCS recupera en milisegundos**, no en horas como Glacier Deep Archive. Para evidencia
  de auditoria es una ventaja real: lo archivado sigue siendo consultable de inmediato.
- **Maximo de 1.000 condiciones `matchesPrefix`/`matchesSuffix` combinadas** entre todas las reglas del
  bucket. No intente una regla por tenant.
- **CMEK no es cifrado de campo.** Protege en reposo a nivel de servicio. Si el requisito es que el
  operador de la plataforma no pueda leer datos de un tenant, hace falta cifrado de aplicacion con la
  llave del tenant (modulo `gcp/kms`).
- `uniform_bucket_level_access` desactiva las ACL por objeto. Es lo correcto, pero rompe cualquier
  integracion heredada que dependa de ACL.
