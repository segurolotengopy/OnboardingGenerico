# Modulo `gcp/orchestration`

## Que crea

- **Cloud Workflow** `og-{env}-onboarding-saga` con la saga completa: resolucion de plan, verificaciones
  en paralelo, scoring y espera de decision humana con callback endpoint.
- **Dos colas de Cloud Tasks**: una para verificaciones internas y otra, mucho mas limitada, para
  llamadas facturables a proveedores externos.
- **Topico y suscripcion de Pub/Sub** para eventos de dominio, con topico de mensajes fallidos,
  entrega exactamente una vez y ordenacion opcional.
- **Trigger de Eventarc** sobre cambios en la coleccion de casos de Firestore.

El codigo del workflow se genera con `yamlencode()` sobre una estructura HCL, de modo que las URLs de
servicio y los tiempos de espera son variables y no cadenas cableadas.

## Advertencias

- 🔴 **512 KB acumulados por ejecucion.** Es el limite mas restrictivo de todo el diseno de GCP:
  variables mas argumentos mas eventos, sumados a lo largo de **toda** la ejecucion. No es por paso.
  Step Functions permite 256 KiB por payload sin acumulado. Por eso el workflow transporta
  exclusivamente punteros `gs://` y jamas resultados de OCR.
- 🔴 **El callback tiene 12 horas por defecto y UN SOLO SLOT pendiente por endpoint** (un segundo
  callback recibe HTTP 429), y **no hay heartbeat**. **PENDIENTE DE VERIFICAR:** no esta documentado un
  maximo por encima de las 12 horas. Una revision manual que cruce un fin de semana o escale a
  compliance **no cabe**. El patron alternativo, sin techo, es: persistir el estado en Firestore,
  terminar el workflow, y lanzar una ejecucion nueva con `executions.run` cuando llegue la decision.
  Cuota adicional: **1.500 peticiones de callback por minuto y ubicacion**.
- **No hay tier Express.** El equivalente a los hijos Express se construye con Cloud Tasks (deadline
  HTTP de 10 minutos por defecto, **30 minutos maximo**; tarea de 1 MiB; 500 despachos/s por cola).
- **No hay Distributed Map.** Para fan-out masivo, use jobs de Cloud Run con `task_count`.
- **Otros limites de Workflows:** respuesta HTTP 2 MB, longitud de cadena 256 KB, 100.000 pasos por
  ejecucion, **10 ramas por paso `parallel`**, 2 niveles de anidamiento paralelo, 20 iteraciones
  concurrentes antes de encolar, profundidad de pila 20, codigo fuente 128 KB, **expresiones de 400
  caracteres** (obliga a partir la logica en pasos `assign`), retencion de ejecuciones 90 dias.
- **La traduccion desde ASL no es mecanica.** El lenguaje es YAML con CEL, no hay intrinsic functions
  ni integraciones optimizadas de SDK. Prevea **reescribir** el orquestador, no portarlo. En el
  hexagono, el puerto de saga debe exponer operaciones de dominio (`iniciarVerificacion`,
  `esperarDecisionManual`), no primitivas de ninguna de las dos nubes.
- **Firestore con Eventarc no garantiza orden y no permite reproduccion del stream.** Si la saga
  depende del orden por caso, active `enable_message_ordering` y publique con el `caseId` como clave
  (a costa de 1 MBps por clave), o incluya un numero de secuencia en el documento y reordene en el
  consumidor. Para reprocesar, itere la coleccion; no hay stream que rebobinar.
- **`call_log_level = LOG_ALL_CALLS` registra cuerpos de peticion.** En eKYC eso vuelca metadatos de PII
  a Cloud Logging. El valor por defecto de este modulo es `LOG_ERRORS_ONLY`.
- La cola de proveedores externos usa **dos intentos como maximo** a proposito: cada reintento se
  factura al proveedor. Las operaciones no idempotentes deben ir por esa cola, no por la general.
