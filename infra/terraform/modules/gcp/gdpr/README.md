# Modulo `gcp/gdpr`

## Que crea

- **Job de Cloud Run de purga**, con timeout largo y reintentos.
- **Permisos de borrado** sobre los buckets suprimibles, Firestore y las llaves de tenant. Son los
  unicos permisos de borrado de todo el sistema, y viven en una identidad **distinta** de la del
  runtime.
- **Trigger de Eventarc** sobre la coleccion de solicitudes de supresion, con topico de mensajes
  fallidos como transporte.
- **Barrido programado** con Cloud Scheduler.
- **Metrica y dos politicas de alerta** de cumplimiento.

## Advertencias

- 🔴 **El borrado suave de Cloud Storage retiene los objetos 7 dias y esta activo por defecto.** El
  modulo `gcp/storage` lo desactiva de forma explicita. Si alguien lo reactiva, un borrado deja de ser
  un borrado **y nada falla**: el incumplimiento es silencioso. Verifiquelo en cada auditoria.
- 🔴 **Firestore con Eventarc no permite reproducir el stream.** Si el trigger falla, o no existia
  cuando se creo la solicitud, no hay forma de rebobinar: hay que iterar la coleccion. Por eso el
  **barrido programado no es un extra**, es parte del mecanismo. En AWS, DynamoDB Streams si permite
  reproceso dentro de su ventana de 24 horas.
- 🔴 **La evidencia bajo Bucket Lock no puede borrarse.** La unica via es el **crypto-shredding** de la
  llave del tenant, y Cloud KMS **no permite destruccion inmediata**: la version queda restaurable
  durante `destroy_scheduled_duration` (30 dias por defecto). Cualquier promesa contractual de borrado
  debe ser compatible con ese plazo. **PENDIENTE DE VERIFICAR** el minimo configurable.
- 🔴 **El TTL de Firestore no borra subcolecciones** y no es transaccional: los documentos expirados
  siguen apareciendo en consultas hasta que desaparecen de verdad, "tipicamente dentro de 24 horas". No
  sirve para acreditar cumplimiento.
- **Eventarc no puede ejecutar un job directamente.** Dispara un servicio de Cloud Run que lanza la
  ejecucion del job. Es un salto mas que en AWS, donde el stream invoca la funcion directamente, y un
  punto de fallo adicional que hay que vigilar.
- **Con versionado activo hay que borrar todas las versiones del objeto**, no solo la actual. El rol
  `storage.objectAdmin` lo permite; el codigo debe hacerlo de forma explicita.
- **Separe la identidad de purga de la del runtime.** Si el runtime pudiera borrar, cualquier fallo de
  logica se convertiria en perdida de datos irreversible.
- **Retencion contra supresion es una tension real.** Las obligaciones KYC/AML piden conservar de 5 a 10
  anios; el derecho de supresion pide borrar. Se concilian conservando la evidencia minima bajo WORM y
  suprimiendo el resto, con el crypto-shredding como ultimo recurso. Documente que se conserva y bajo
  que base legal.
- **Umbral cero en las alertas.** Una purga fallida no es una anomalia operativa: es un plazo legal
  corriendo.
