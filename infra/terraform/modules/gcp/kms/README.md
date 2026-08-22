# Modulo `gcp/kms`

## Que crea

- **Keyring** regional `og-{env}-keyring`.
- **Llave de plataforma** para la CMEK de los servicios gestionados, con rotacion anual.
- **Una llave por tenant** mediante `for_each`, con `destroy_scheduled_duration` parametrizable.
- **Bindings de IAM**: llave exclusiva para la cuenta de servicio de cada tenant premium, acceso del
  runtime compartido a todas las llaves, y una identidad de operacion separada con permiso para
  programar destrucciones.
- **Autokey** opcional.

## Por que este modulo es el centro del aislamiento en GCP

GCP **no puede** aplicar aislamiento multi-tenant en el plano de datos: no existe equivalente a
`dynamodb:LeadingKeys`. Por eso el cifrado de sobre por tenant deja de ser defensa en profundidad
opcional y pasa a ser el **control primario**:

```
Datos cifrados con DEK, envuelta por la llave (KEK) del tenant
AAD = tenant_id | record_id
=> un error de alcance produce un FALLO DE DESCIFRADO, no una fuga
```

Esa es la propiedad que hace portable el multi-tenancy a GCP. Trátela como requisito, no como extra.

## Advertencias

- 🔴 **No existe equivalente al AWS Database Encryption SDK.** Tink cubre el cifrado de sobre y el AAD,
  pero **no** la firma del registro completo, **ni** los atributos firmados-pero-no-cifrados, **ni** los
  beacons de busqueda sobre campos cifrados. Si el diseno de AWS consulta por campos cifrados usando
  beacons, **ese patron no se porta**: hay que reimplementarlo con un indice HMAC determinista con
  clave por tenant, asumiendo el analisis de fuga de frecuencia.
- 🔴 **Tink no trae cache de material criptografico.** Hay un problema de rendimiento conocido con
  Envelope AEAD sobre Cloud KMS por la latencia de la llamada por operacion. **La cache no es opcional,
  es requisito de viabilidad**: cachee el objeto `Aead` derivado por tenant en memoria del proceso, con
  TTL y limite de mensajes y bytes.
- 🔴 **Tink no tiene version JavaScript/TypeScript mantenida.** Si algun componente fuera Node.js, seria
  un bloqueante real: haria falta un sidecar en Go o Java, o implementar el sobre directamente contra
  la API de Cloud KMS. (Este proyecto es Python, donde Tink si esta soportado.)
- 🔴 **Crypto-shredding no es inmediato.** Cloud KMS **no permite destruccion inmediata**: se programa y
  la version queda restaurable durante `destroy_scheduled_duration`, con **30 dias por defecto**.
  **PENDIENTE DE VERIFICAR:** el minimo configurable no aparece en la documentacion de destruccion y
  restauracion (se cita habitualmente 24 h, sin confirmar). Verifiquelo antes de comprometer un SLA. La
  organizacion puede ademas imponer un minimo con
  `constraints/cloudkms.minimumDestroyScheduledDuration`.
- **Los keyrings y las llaves de Cloud KMS no se pueden borrar.** Existen para siempre en el proyecto.
  `prevent_destroy` esta puesto en las llaves para que Terraform no intente algo que el servicio no
  permite y deje el estado inconsistente. Planifique la nomenclatura con eso en mente.
- **La ubicacion del keyring debe coincidir con la de los recursos que cifra.** Una llave regional no
  puede cifrar un recurso de otra region.
- **CMEK no es cifrado de campo.** Protege en reposo a nivel de servicio. No confunda CMEK con lo que
  hace el cifrado de aplicacion por tenant.
- **Autokey no soporta Firestore.** Su CMEK se declara de forma explicita en `gcp/data`. Ademas, los
  key handles de Autokey **no aparecen en Cloud Asset Inventory**, lo que complica el inventario.
- **El sobre anade tamano**: DEK envuelta, nonce y tag suman del orden de 100 a 200 bytes por campo
  cifrado. Con el limite de 1 MiB por documento de Firestore y 64 KiB por secreto de Secret Manager,
  eso importa cuando hay muchos campos.
- **El runtime compartido puede usar todas las llaves de tenant.** No es un descuido: es la constatacion
  de que IAM no puede separarlas por fila. La barrera efectiva es el AAD.
