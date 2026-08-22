# Paridad AWS → GCP para middleware serverless de onboarding/eKYC

**Fecha de investigación:** 21 de agosto de 2026. Todo verificado contra documentación oficial salvo donde se indica explícitamente lo contrario.

> **Hallazgo transversal que afecta a todo el diseño:** Vertex AI fue renombrado a **Gemini Enterprise Agent Platform** (mayo 2026). La documentación de Vertex AI "ya no se actualiza" y redirige a `docs.cloud.google.com/gemini-enterprise-agent-platform/`. Los recursos Terraform siguen llamándose `google_vertex_ai_*` y el endpoint de API sigue siendo `aiplatform.googleapis.com`, pero **la nomenclatura del puerto en el núcleo hexagonal no debe acoplarse a "Vertex"**. Fuente: [Vertex AI deprecations](https://docs.cloud.google.com/vertex-ai/docs/deprecations).

---

## 1. Tabla maestra de equivalencias

| # | Capacidad | AWS (referencia) | GCP (alternativa) | Paridad | Recurso Terraform principal |
|---|---|---|---|---|---|
| 1 | API Gateway + authorizer | API Gateway + Lambda Authorizer + Cognito | API Gateway / Apigee / Cloud Run + Identity Platform / IAP | ⚠️ Parcial — **no hay authorizer de código arbitrario** | `google_api_gateway_gateway`, `google_identity_platform_tenant` |
| 2 | Workflows larga duración | Step Functions Standard (1 año) | Cloud Workflows (1 año) | ✅ Buena | `google_workflows_workflow` |
| 2b | Workflows baja latencia | Step Functions Express (5 min) | Cloud Workflows / Cloud Tasks / Eventarc | ⚠️ Modelo distinto (sin tier "Express") | `google_cloud_tasks_queue`, `google_eventarc_trigger` |
| 2c | `waitForTaskToken` | Task token + heartbeat, hasta 1 año | `events.create_callback_endpoint` + `await_callback`, **12 h por defecto, 1 slot** | ⚠️ Parcial | (dentro del YAML del workflow) |
| 3 | Cómputo contenedor | Lambda container 10 GB / 10.240 MB / 15 min | Cloud Run services / jobs / functions — 32 GiB, 8 vCPU, 60 min | ✅ **GCP superior** | `google_cloud_run_v2_service`, `google_cloud_run_v2_job` |
| 4 | NoSQL K-V + streams + TTL | DynamoDB + Streams + TTL | Firestore (Native/Datastore), Bigtable, Spanner | ⚠️ Parcial — TTL sí, "streams" vía Eventarc (semántica distinta) | `google_firestore_database`, `google_firestore_field` |
| 5 | Objetos + ciclo de vida | S3 + Lifecycle + Glacier | Cloud Storage + OLM + Coldline/Archive | ✅ Buena (Archive **mejor**: latencia ms) | `google_storage_bucket` (`lifecycle_rule`) |
| 6 | KMS + cifrado de sobre | KMS CMK + AWS Encryption SDK / **DB-ESDK** | Cloud KMS + Autokey + **Tink** | ⚠️ Parcial — **no existe DB-ESDK** | `google_kms_crypto_key`, `google_kms_autokey_config` |
| 7 | Aislamiento multi-tenant | STS session tags + `dynamodb:LeadingKeys` | IAM Conditions, WIF attribute conditions, proyectos/BD por tenant | ❌ **Sin equivalente directo** | `google_project_iam_member` (`condition`), `google_iam_workload_identity_pool_provider` |
| 8 | OCR de documentos ID | Textract `DetectDocumentText` / `AnalyzeID` | Document AI (Enterprise OCR + ID processors) | ⚠️ OCR sí; **cobertura de países mucho menor** | `google_document_ai_processor` |
| 9 | LLM multimodal + caching | Bedrock + Claude + prompt caching | Agent Platform (ex-Vertex) + **Claude** + Gemini context caching | ✅ Buena | `google_vertex_ai_endpoint` (modelos gestionados: sin TF) |
| 10 | Biometría facial + liveness | Rekognition `CompareFaces` + Face Liveness | **Nada gestionado** | ❌ **Sin equivalente** | (Cloud Run + modelo propio) |
| 11 | Human-in-the-loop | SageMaker A2I (**cerrado a nuevos clientes**) | **Nada gestionado** (HITL y Data Labeling apagados) | ❌ **Sin equivalente** | (construcción propia) |
| 12 | Observabilidad y auditoría | CloudWatch, X-Ray, CloudTrail | Cloud Logging, Cloud Trace, Cloud Audit Logs | ✅ Buena | `google_logging_project_sink`, `google_project_iam_audit_config` |
| 13 | Secretos y config | Secrets Manager + Parameter Store | Secret Manager | ⚠️ **No hay equivalente a Parameter Store** | `google_secret_manager_secret` |
| 14 | Registro de contenedores | ECR | Artifact Registry | ✅ Buena (multi-formato, **mejor**) | `google_artifact_registry_repository` |
| 15 | Red privada / egreso | VPC + PrivateLink + VPC endpoints | VPC + Private Service Connect + Direct VPC egress | ✅ Buena | `google_compute_service_attachment`, `google_vpc_access_connector` |

---

## 2. Notas detalladas por capacidad

### 1. Puerta de entrada de API + autorizador

**AWS:** API Gateway (REST/HTTP) + Lambda Authorizer (TOKEN/REQUEST, caché hasta 3600 s) + Cognito User Pools (authorizer nativo, multi-tenant vía user pools o `custom:tenant_id`).

**GCP — tres opciones, ninguna idéntica:**

| Opción | Cuándo usarla | Límites verificados |
|---|---|---|
| **API Gateway** | Fachada ligera sobre Cloud Run/Functions | 50 APIs/proyecto, 100 configs/API, 50 gateways/región; request/response **32 MB**; headers 60 KB; 10.000.000 unidades de cuota/100 s; **sin streaming** |
| **Cloud Endpoints (ESPv2)** | Necesitas el proxy como sidecar en tu propio Cloud Run | Mismo motor ESPv2 que API Gateway |
| **Apigee X** | Gobernanza real de API, políticas custom, monetización | Coste base muy superior; despliegue con `google_apigee_organization` + `google_apigee_instance` |
| **Cloud Run + IAP** | Front-end interno/corporativo | IAP soporta `request.auth.access_levels`, `request.host`, `request.path` en IAM Conditions |

**Diferencia funcional crítica:** GCP API Gateway **no tiene Lambda Authorizer**. Solo soporta métodos declarativos: API keys, service accounts con JWT firmado, y validación JWT contra emisores (Firebase, Auth0, Okta, Google ID token, o emisor custom vía `x-google-issuer` / `x-google-jwks_uri` en el OpenAPI). No hay forma de ejecutar código arbitrario por petición en el gateway.

**Mitigación para el hexágono:** el puerto `AuthorizationPort` debe implementarse en AWS con Lambda Authorizer y en GCP como **middleware in-process dentro del Cloud Run** (valida el JWT, resuelve tenant, aplica políticas). Esto es en realidad más portable: mueve la lógica de autorización fuera del adaptador de infraestructura.

**Cognito → Identity Platform:** multi-tenancy nativa. Con instrumento de facturación los tenants son **ilimitados**; sin él, solo **2 tenants/proyecto**. Cuentas registradas ilimitadas, anónimas hasta 100 M. Límites de tasa: 45.000 sign-ins/min con custom token, 18.000 intercambios de token/min, 1.600 sign-ins/min por teléfono, creación de cuentas 100/hora **por IP**. Cada tenant tiene sus propios IdPs (email/password, social, SAML, OIDC). No soporta deshabilitar account linking ni blocking functions por tenant.

**Advertencias de portabilidad:**
- API Gateway (GCP) es de **desarrollo lento**; para eKYC con políticas complejas, Apigee o el propio Cloud Run son apuestas más seguras.
- El límite de 32 MB de request es relevante si subes imágenes de documentos por el gateway: **usa URLs firmadas de GCS en su lugar** (patrón que ya deberías usar en S3).
- Cognito devuelve tokens con `cognito:groups`; Identity Platform usa **custom claims** (`setCustomUserClaims`). El puerto debe normalizar a un `TenantContext` propio.

Fuentes: [API Gateway quotas](https://docs.cloud.google.com/api-gateway/docs/quotas) · [Authentication methods](https://docs.cloud.google.com/api-gateway/docs/authentication-method) · [Identity Platform multi-tenancy](https://docs.cloud.google.com/identity-platform/docs/multi-tenancy) · [Identity Platform quotas](https://docs.cloud.google.com/identity-platform/quotas)

**Terraform:** `google_api_gateway_api`, `google_api_gateway_api_config`, `google_api_gateway_gateway` (históricamente solo en `google-beta`; verifica la versión de tu provider) · `google_identity_platform_config`, `google_identity_platform_tenant`, `google_identity_platform_tenant_oauth_idp_config` · `google_apigee_organization` / `_instance` / `_environment` / `_envgroup` · `google_endpoints_service` · `google_iap_settings`, `google_iap_web_backend_service_iam_member`

---

### 2. Orquestación de workflows

#### Duración máxima de Cloud Workflows

**Un año**, igual que Step Functions Standard. Confirmado en [Workflows quotas](https://docs.cloud.google.com/workflows/quotas).

#### ¿Existe equivalente a `waitForTaskToken`?

**Sí, pero limitado.** Se llama **callback endpoints**:

```yaml
- create_callback:
    call: events.create_callback_endpoint
    args:
      http_callback_method: "POST"
    result: callback_details
- await_response:
    call: events.await_callback
    args:
      callback: ${callback_details}
      timeout: 43200          # 12 h por defecto
    result: callback_request
```

**Diferencias frente a Step Functions:**

| Aspecto | Step Functions `waitForTaskToken` | Cloud Workflows callback |
|---|---|---|
| Timeout | Hasta 1 año (`TimeoutSeconds`) | **Default 43.200 s (12 h)**; el parámetro es configurable pero **no pude verificar un máximo documentado por encima de 12 h** |
| Callbacks concurrentes | Muchos tokens en paralelo | **1 slot por endpoint**; un segundo callback recibe **HTTP 429** |
| Heartbeat | `SendTaskHeartbeat` nativo | **No existe** |
| Éxito/fallo explícito | `SendTaskSuccess` / `SendTaskFailure` | Un solo POST; el resultado se codifica en el body |
| Cuota | — | **1.500 peticiones de callback/min por ubicación** |

Para eKYC esto es material: un flujo de revisión manual que dure más de 12 h (fin de semana, escalado a compliance) **necesita** o bien confirmar que el timeout admite valores mayores, o bien un patrón alternativo: persistir el estado en Firestore, terminar el workflow, y lanzar un workflow nuevo con `executions.run` cuando llegue la decisión.

#### Límites de Cloud Workflows que rompen portajes directos

| Límite | Valor | Impacto en eKYC |
|---|---|---|
| **Datos acumulados por ejecución** | **512 KB** (variables + argumentos + eventos) | 🔴 **Crítico.** No puedes pasar imágenes ni respuestas OCR completas por el estado del workflow. Step Functions permite 256 KB por payload pero sin acumulado. Usa punteros a GCS. |
| Respuesta HTTP | 2 MB | Las llamadas a Document AI deben devolver referencias, no el documento completo |
| Longitud de string | 256 KB | |
| Pasos por ejecución | 100.000 | |
| Ramas por paso `parallel` | 10 | vs. Step Functions Map con concurrencia 40+ |
| Anidamiento paralelo | 2 niveles | |
| Iteraciones concurrentes | 20 antes de encolar | |
| Profundidad de call stack | 20 | |
| Ejecuciones concurrentes | 10.000/región/proyecto | |
| Retención de ejecuciones | 90 días | vs. CloudTrail/SFN history 90 días — paridad |
| Tamaño del código fuente | 128 KB | |
| Longitud de expresión | 400 caracteres | Fuerza a partir lógica en pasos `assign` |

#### No hay "Express" — cómo se cubre la baja latencia

Cloud Workflows tiene un único tier. Para el equivalente a Step Functions Express:

- **Cloud Tasks**: cola con reintentos y despacho HTTP. Tamaño de tarea **1 MiB**, dispatch **500 tareas/s por cola**, programación hasta **30 días** en el futuro, retención **31 días**, deduplicación hasta 24 h, 1.000 colas/región. **Deadline HTTP: default 10 min, máximo 30 min.** Es el mejor sustituto de `waitForTaskToken` para pasos asíncronos cortos.
- **Pub/Sub**: mensaje hasta **10 MB**, retención de suscripción 7 días (default) hasta 31 días, exactly-once delivery y ordering keys (1 MBps por clave), 10.000 suscripciones/topic.
- **Eventarc**: routing declarativo de eventos de Google Cloud (incluidos Firestore y GCS) hacia Cloud Run/Workflows.

**Advertencias de portabilidad:**
- Workflows **no tiene un `Map` distribuido** equivalente al Distributed Map de Step Functions (10.000 ejecuciones hijas). Para fan-out masivo usa Cloud Run **jobs** con `task_count` hasta 10.000.
- El lenguaje es **YAML/CEL**, no ASL. La traducción no es mecánica: prevé reescribir el orquestador, no portarlo. En el hexágono, el `OnboardingSagaPort` debe exponer operaciones de dominio (`iniciarVerificacion`, `esperarDecisionManual`), no primitivas de Step Functions.
- Workflows no tiene equivalente a los **intrinsic functions** de ASL ni al catálogo de integraciones optimizadas de SDK (`arn:aws:states:::aws-sdk:*`). Todo se hace con `http.post` o conectores.

**Terraform:** `google_workflows_workflow` · `google_cloud_tasks_queue` · `google_eventarc_trigger`, `google_eventarc_channel` · `google_pubsub_topic`, `google_pubsub_subscription` · `google_cloud_scheduler_job`

Fuentes: [Workflows quotas](https://docs.cloud.google.com/workflows/quotas) · [Wait using callbacks](https://docs.cloud.google.com/workflows/docs/creating-callback-endpoints) · [Cloud Tasks quotas](https://docs.cloud.google.com/tasks/docs/quotas) · [Create HTTP target tasks](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks) · [Pub/Sub quotas](https://docs.cloud.google.com/pubsub/quotas)

---

### 3. Cómputo serverless con contenedores y ONNX pesados

| Dimensión | Lambda (container) | Cloud Run service | Cloud Run job | Cloud Run function (2ª gen) |
|---|---|---|---|---|
| Memoria máx. | 10.240 MB | **32 GiB** | 32 GiB | 32 GB |
| CPU máx. | 6 vCPU (a 10 GB) | **8 vCPU** | 8 vCPU | — |
| Timeout | 15 min | **60 min** | **168 h (7 días)**; 1 h con GPU | 60 min HTTP / 30 min scheduled / **9 min event-driven** |
| Imagen | 10 GB descomprimida | **Sin límite documentado** | Sin límite | 100 MB comprimido (1ª gen) |
| Concurrencia | 1 petición/instancia | **Hasta 1.000/instancia** | N/A | Configurable |
| GPU | No | **Sí** (L4, RTX PRO 6000) | Sí | No |
| FS escribible | `/tmp` hasta 10 GB | **In-memory, cuenta contra la memoria** (32 GiB) | Idem | Idem |
| Arranque | Init hasta 10 s | **Startup timeout 4 min** | — | — |

**Relación CPU↔memoria obligatoria en Cloud Run** (no existe en Lambda, donde la CPU escala con la memoria automáticamente):

| vCPU | Memoria permitida |
|---|---|
| 0,08 | hasta 512 MiB |
| 1 | hasta 4 GiB |
| 4 | 2–16 GiB |
| 8 | **4–32 GiB** |

**GPU (agosto 2026):**

| GPU | VRAM | CPU mín. | Memoria mín. | Regiones |
|---|---|---|---|---|
| NVIDIA L4 | 24 GB | 4 | 16 GiB (32 recomendado) | `us-central1`, `us-east4`, `europe-west1`, `europe-west4`, `asia-southeast1`, `asia-south1` (invitación) |
| RTX PRO 6000 Blackwell | 96 GB | 20 | 80 GiB | `us-central1`, `europe-west4`, `asia-southeast1`, `asia-south2` |

- Cuota inicial automática: **3 L4** o **3.000 milliGPU** por proyecto; más requiere solicitud.
- **Cold start con GPU ≈ 5 segundos** (drivers preinstalados) — competitivo.
- **1 GPU por instancia**, facturación basada en instancia.
- ⚠️ **Inconsistencia detectada en la documentación:** el requisito de 80 GiB de memoria para RTX PRO 6000 contradice el máximo documentado de 32 GiB por instancia. **No pude reconciliar esto**; verifícalo antes de dimensionar.

**Recomendación para ONNX pesados:** Cloud Run **service** con `min_instances ≥ 1`, **startup CPU boost** activado, y el modelo **horneado en la imagen** (no descargado de GCS en arranque). La ausencia de límite de tamaño de imagen es una ventaja real frente a los 10 GB de Lambda: puedes empaquetar ONNX Runtime + modelos de detección facial + OCR auxiliar en una sola imagen.

**Advertencias de portabilidad:**
- 🔴 **El sistema de archivos escribible de Cloud Run es tmpfs y consume memoria.** Si el adaptador Lambda usa `/tmp` para escribir imágenes intermedias asumiendo disco, en Cloud Run eso reduce la memoria disponible para el modelo. Alternativas: montaje de volumen **Cloud Storage FUSE** o **Filestore/NFS**.
- 🔴 **Concurrencia > 1 cambia el modelo de ejecución.** Lambda garantiza una petición por instancia; ONNX Runtime con concurrencia 80 en Cloud Run necesita sesiones thread-safe y control de hilos intra-op, o saturarás CPU. Fija `concurrency = 1..4` para inferencia pesada.
- Las **event-driven functions** tienen tope de **9 minutos**, mucho menos que Lambda (15 min). Para procesado de documentos por evento, usa Cloud Run service con Eventarc, no Cloud Run functions.
- **Direct VPC egress limita las instancias máximas a 100–200 según región**: si necesitas alta escala *y* red privada, revisa esa cuota temprano.

**Terraform:** `google_cloud_run_v2_service` (bloque `template.containers.resources.limits`, `node_selector` para GPU, `gpu_zonal_redundancy_disabled`), `google_cloud_run_v2_job`, `google_cloud_run_v2_worker_pool`, `google_cloud_run_v2_service_iam_member`

Fuentes: [Cloud Run quotas](https://docs.cloud.google.com/run/quotas) · [Memory limits](https://docs.cloud.google.com/run/docs/configuring/services/memory-limits) · [GPU support](https://docs.cloud.google.com/run/docs/configuring/services/gpu) · [Functions quotas](https://docs.cloud.google.com/functions/quotas)

---

### 4. NoSQL clave-valor con streams y TTL

#### ¿Firestore tiene TTL? **Sí.**

- Política TTL sobre un campo `Timestamp` designado, por **grupo de colecciones**.
- **Un solo campo TTL por grupo de colecciones**; máximo 1.000 configuraciones a nivel de campo.
- ⚠️ **Borrado "típicamente dentro de 24 h tras la expiración"**, no garantizado ni transaccional. Documentos expirados **siguen apareciendo en consultas** hasta que se borran de verdad. DynamoDB TTL tiene la misma característica (borrado típico en 48 h), así que hay paridad conceptual — **pero para cumplimiento GDPR/retención de datos KYC ninguno de los dos sirve como mecanismo de borrado garantizado.**
- 🔴 **El TTL no borra subcolecciones.** Si modelas `/tenants/{t}/casos/{c}/documentos/{d}`, expirar el caso deja las subcolecciones huérfanas. DynamoDB no tiene este problema porque no hay jerarquía.

#### ¿Firestore tiene change streams? **Sí, pero la semántica no es la de DynamoDB Streams.**

Firestore emite eventos a **Eventarc** (`google.cloud.firestore.document.v1.created/updated/deleted/written`) que se enrutan a Cloud Run, Cloud Run functions, GKE o Workflows. Desde 2024 el soporte se extendió también a **modo Datastore**.

| Aspecto | DynamoDB Streams | Firestore + Eventarc |
|---|---|---|
| Orden | Garantizado **por clave de partición** dentro de un shard | ❌ **Sin garantía de orden estricto** |
| Entrega | At-least-once, iterador de 24 h | At-least-once vía Pub/Sub |
| Reproceso histórico | Sí, 24 h de retención de shard | ❌ **No hay replay del stream**; retención según la suscripción Pub/Sub subyacente |
| Batching | Lambda recibe lotes (hasta 10.000 registros) | Un evento por invocación |
| Imagen previa/posterior | `OLD_IMAGE`, `NEW_IMAGE`, `NEW_AND_OLD_IMAGES` | `oldValue` y `value` en el payload |
| Tamaño de evento | 400 KB (tamaño de ítem) | **512 KB** (límite de evento Eventarc en Cloud Run functions 2ª gen) |

#### ¿Cómo se emula el patrón single-table?

**Respuesta honesta: no se emula bien, y probablemente no deberías intentarlo.**

DynamoDB single-table se apoya en tres cosas que Firestore no tiene: clave compuesta PK+SK con consultas por rango sobre SK, GSIs con proyección arbitraria, y `begins_with` sobre la sort key.

Opciones, de mejor a peor:

1. **Firestore Native con IDs de documento compuestos** — replica `PK#SK` como ID del documento dentro de una colección plana y usa consultas de rango sobre `__name__`. Funciona para `begins_with` porque los IDs se ordenan lexicográficamente. Es el mapeo más fiel.
2. **Cloud Bigtable** — es el equivalente estructural más cercano a DynamoDB: row key ordenada lexicográficamente, prefijos, column families. **Si tu single-table es agresiva, Bigtable es el destino correcto, no Firestore.** Contra: no es serverless en coste (nodos provisionados), no tiene TTL por ítem sino **garbage collection por column family**, y no tiene change streams en el mismo sentido.
3. **Spanner** — si el modelo de acceso realmente es relacional disfrazado. Tiene interleaved tables, TTL con `ROW DELETION POLICY`, y **change streams reales con orden y replay de hasta 7 días**. Es la única opción de GCP con paridad real de streams. Contra: coste y complejidad muy superiores.
4. **Firestore Enterprise edition** (compatible con MongoDB) — nueva, permite TTL sobre timestamps dentro de arrays.

**Límites de Firestore verificados:** 100 bases de datos/proyecto (ampliable), documento **1 MiB**, nombre de documento 6 KiB, ID de colección/documento ≤ 1.500 bytes, 1.000 índices compuestos, 40.000 entradas de índice por documento, transacción **270 s** (60 s idle), request API **10 MiB**.

**Advertencias de portabilidad:**
- 🔴 El **límite de 1 MiB por documento** vs. **400 KB por ítem de DynamoDB**: Firestore es más generoso, pero cuidado con los **40.000 índices por documento** — un documento con mapas anidados grandes revienta ese límite antes que el de tamaño. Desactiva la indexación de campos que no consultas (`google_firestore_field` con `index_config` vacío).
- Firestore soporta **múltiples bases de datos por proyecto (100)**: esto habilita el patrón **base de datos por tenant** para tenants grandes, algo que DynamoDB solo consigue con tablas separadas.
- El **puerto de repositorio** del hexágono debe exponer operaciones de dominio (`buscarCasosPorTenantYEstado`), nunca `query(PK, SK begins_with ...)`. Si tu puerto actual filtra PK/SK, ya está acoplado a DynamoDB y ese es el primer refactor.

**Terraform:** `google_firestore_database`, `google_firestore_field` (bloque `ttl_config {}`), `google_firestore_index`, `google_firebaserules_ruleset`, `google_firebaserules_release` · `google_bigtable_instance`, `google_bigtable_table`, `google_bigtable_gc_policy`, `google_bigtable_app_profile` · `google_spanner_instance`, `google_spanner_database`

Fuentes: [Firestore TTL](https://docs.cloud.google.com/firestore/native/docs/ttl) · [Firestore quotas](https://docs.cloud.google.com/firestore/native/docs/quotas) · [Eventarc con Firestore](https://docs.cloud.google.com/firestore/native/docs/eventarc) · [Datastore mode + Eventarc](https://docs.cloud.google.com/datastore/docs/eventarc) · [Firestore extends triggering to Datastore mode](https://cloud.google.com/blog/products/databases/firestore-extends-triggering-support-to-include-datastore-mode/)

---

### 5. Almacenamiento de objetos con ciclo de vida

**Paridad alta.** Es la capacidad que se porta con menos fricción.

| Clase GCS | Duración mínima | Equivalente AWS | Nota |
|---|---|---|---|
| Standard | ninguna | S3 Standard | SLA 99,9 % regional |
| Nearline | **30 días** | S3 Standard-IA | SLA 99,0 % |
| Coldline | **90 días** | S3 Glacier Instant Retrieval | SLA 99,0 % |
| Archive | **365 días** | S3 Glacier Deep Archive | 🟢 **Ventaja GCP: recuperación en milisegundos, no horas** |

**Acciones OLM:** `Delete`, `SetStorageClass`, `AbortIncompleteMultipartUpload`.
**Condiciones:** `age`, `createdBefore`, `customTimeBefore`, `daysSinceCustomTime`, `daysSinceNoncurrentTime`, `noncurrentTimeBefore`, `numNewerVersions`, `matchesPrefix`/`matchesSuffix` (máx. 1.000 combinados entre reglas), `matchesStorageClass`, `sizeAboveBytes`/`sizeBelowBytes`.

**Advertencias de portabilidad:**
- ⚠️ **Los cambios de configuración de lifecycle tardan hasta 24 h en surtir efecto**, y la ejecución es asíncrona (la acción puede ir muy por detrás del cumplimiento de la condición). Idéntico a S3.
- 🔴 **Soft-delete está activo por defecto en GCS**: los objetos borrados se retienen **7 días**. Para eKYC con derecho al olvido, esto significa que un `Delete` no es un borrado. Debes desactivar la soft-delete policy explícitamente o documentar la ventana. **S3 no tiene este comportamiento por defecto.**
- `SetStorageClass` **actualiza el modification time** del objeto y cuenta como operación Clase A (coste). Esto puede resetear reglas basadas en `age` mal escritas.
- Transiciones válidas: Standard → Nearline/Coldline/Archive. No todas las transiciones inversas están permitidas.
- El equivalente a S3 Object Lock / retención WORM es **Bucket Lock** (`retention_policy` con `is_locked`), y el equivalente a Object Lock por objeto es **Object Retention Lock**.

**Terraform:** `google_storage_bucket` (bloques `lifecycle_rule`, `retention_policy`, `soft_delete_policy`, `versioning`, `encryption.default_kms_key_name`), `google_storage_bucket_iam_member`, `google_storage_hmac_key`

Fuentes: [Object Lifecycle Management](https://docs.cloud.google.com/storage/docs/lifecycle) · [Storage classes](https://docs.cloud.google.com/storage/docs/storage-classes)

---

### 6. Gestión de claves y cifrado de sobre por tenant

#### ¿Existe un equivalente al AWS Database Encryption SDK (DB-ESDK)? **No.**

El DB-ESDK de AWS es una biblioteca específica que hace cifrado a nivel de atributo en DynamoDB, con **firma criptográfica del ítem completo**, **atributos firmados-pero-no-cifrados** (para poder indexarlos), y **beacons de cifrado búsqueda** que permiten consultas de igualdad sobre campos cifrados. **Google Cloud no publica nada equivalente.**

#### ¿Google Tink sirve para cifrado de campos con caché de claves de datos? **Sí, es la respuesta correcta.**

Tink cubre bien la parte de cifrado de sobre:

- **`KmsEnvelopeAead`**: genera un DEK, lo cifra con la KEK de Cloud KMS, y devuelve `[DEK cifrada || ciphertext]`. Es el análogo directo del AWS Encryption SDK.
- **Associated Data (AAD)**: pasa `tenant_id` + `record_id` como AAD para vincular criptográficamente el texto cifrado a su contexto — esto es lo que impide mover un blob cifrado entre tenants.
- **Caché de DEKs**: Tink **no trae un caching de material criptográfico equivalente al `CachingCryptoMaterialsManager` del AWS Encryption SDK**. Debes implementarlo tú: cachea el objeto `Aead` derivado por tenant en memoria del proceso, con TTL y límite de mensajes/bytes. Hay un [issue conocido de rendimiento con Envelope AEAD sobre GCP KMS](https://github.com/google/tink/issues/697) precisamente por la latencia de la llamada a KMS por operación — **el caching no es opcional, es obligatorio para viabilidad**.
- **Lo que NO obtienes de Tink:** firma del registro completo, atributos firmados-no-cifrados, y searchable encryption beacons. Si tu diseño AWS los usa, **eso es trabajo de aplicación en GCP**.

#### Crypto-shredding en Cloud KMS

Este es el punto más importante de esta capacidad para eKYC.

- Cloud KMS **no permite destrucción inmediata**. Cita textual: *"Cloud KMS doesn't let you destroy key versions immediately. Instead, you schedule a key version for destruction. The key version remains in the scheduled for destruction state for a configurable time."*
- **Periodo por defecto: 30 días.** Configurable en la creación de la clave mediante `destroy_scheduled_duration`.
- La organización puede **forzar un mínimo** mediante la restricción de política `constraints/cloudkms.minimumDestroyScheduledDuration`.
- Durante la ventana, la versión puede **restaurarse** (cancelar la destrucción).
- ⚠️ **No pude verificar en la documentación oficial cuál es el valor mínimo configurable** (comúnmente citado como 24 h, pero la página de destroy/restore no lo indica). **Verifícalo antes de comprometer un SLA de borrado.** Si tu política de privacidad promete borrado en X días, X debe ser ≥ `destroy_scheduled_duration` + margen.

**Comparación con AWS:** AWS KMS tiene una ventana de espera de **7 a 30 días** para `ScheduleKeyDeletion`, con mínimo de **7 días**. GCP permite en principio ventanas más cortas (si el mínimo es 24 h), lo que sería **una ventaja para crypto-shredding**, pero el default de 30 días es más conservador que el de AWS.

**Patrón recomendado para clave-por-tenant:**

```
KeyRing por región
 └─ CryptoKey por tenant (destroy_scheduled_duration configurado explícitamente)
     └─ versiones rotadas automáticamente (rotation_period)
Datos: KmsEnvelopeAead(KEK = clave del tenant), AAD = tenant_id|record_id
Borrado del tenant: destruir TODAS las versiones de la CryptoKey del tenant
```

**Cloud KMS Autokey:** automatiza el aprovisionamiento de CMEK cuando se crean recursos compatibles. Soporta **27 servicios** incluyendo Cloud Storage, BigQuery, Bigtable, Spanner, Cloud SQL, Compute, GKE, **Cloud Run**, Pub/Sub, **Secret Manager**, **Artifact Registry**, Apigee, Dataflow. 🔴 **Firestore NO está en la lista.** Restricciones: solo en ubicaciones con Cloud HSM, algoritmo fijo AES-256-GCM, rotación anual por defecto, y los *key handles* **no aparecen en Cloud Asset Inventory**.

**Advertencias de portabilidad:**
- 🔴 El **límite de 64 KiB por secreto de Secret Manager** y el de 1 MiB por documento de Firestore acotan cuánto texto cifrado cabe. El cifrado de sobre añade overhead (DEK cifrada + nonce + tag): presupuesta ~100–200 bytes extra por campo cifrado.
- La CMEK de GCS/Firestore es **cifrado en reposo a nivel de servicio**, no cifrado de campo. **No confundas CMEK con lo que hace el DB-ESDK.** Si el requisito es que el operador de la plataforma no pueda leer datos de un tenant, necesitas Tink a nivel de aplicación, y CMEK es defensa en profundidad adicional.
- Tink existe en Java, Go, Python, C++, Obj-C. **La versión JavaScript/TypeScript fue descontinuada** — si tu middleware es Node.js, esto es un bloqueante real y necesitarás bien un sidecar en Go/Java, bien implementar el envelope directamente contra la API de Cloud KMS (`encrypt`/`decrypt` sobre el DEK).

**Terraform:** `google_kms_key_ring`, `google_kms_crypto_key` (`destroy_scheduled_duration`, `rotation_period`, `version_template`), `google_kms_crypto_key_version`, `google_kms_crypto_key_iam_member`, `google_kms_autokey_config`, `google_kms_key_handle`, `google_kms_ekm_connection` (para External Key Manager)

Fuentes: [Destroy and restore key versions](https://docs.cloud.google.com/kms/docs/destroy-restore) · [Control key version destruction](https://docs.cloud.google.com/kms/docs/control-key-destruction) · [Key version states](https://docs.cloud.google.com/kms/docs/key-states) · [Client-side encryption with Tink and Cloud KMS](https://docs.cloud.google.com/kms/docs/client-side-encryption) · [Envelope encryption](https://docs.cloud.google.com/kms/docs/envelope-encryption) · [Autokey overview](https://docs.cloud.google.com/kms/docs/autokey-overview)

---

### 7. Aislamiento multi-tenant a nivel de plataforma

#### Respuesta directa: **GCP NO tiene un equivalente a `dynamodb:LeadingKeys`.**

Esto no es una opinión. La documentación de IAM Conditions enumera exhaustivamente los atributos disponibles y **ninguno permite condicionar sobre el prefijo de una clave de fila o el ID de un documento**:

| Categoría | Atributos disponibles |
|---|---|
| Recurso | `resource.type`, `resource.name`, `resource.service`, `resource.matchTag()` |
| Petición | `request.time`, `request.auth.access_levels` (solo IAP), `request.host`/`request.path` (solo IAP), `destination.ip`/`destination.port` (solo IAP TCP), `api.getAttribute()` |
| Principal | `principal.type`, `principal.subject` |

Además, *"solo algunos tipos de recurso aceptan condiciones en los bindings de rol"* — **Firestore no expone condiciones a nivel de documento en IAM.**

Y el complemento del problema: **las Security Rules de Firestore no sirven para un backend.** Cita textual de la documentación: *"The server client libraries bypass all Firestore Security Rules and instead authenticate through Google Application Default Credentials."* Las Security Rules **solo protegen SDKs de cliente móvil/web**. Un middleware server-side las ignora por completo.

Esto significa que el modelo de AWS —donde asumes un rol con `sts:AssumeRole` + session tag `tenant_id`, y DynamoDB **rechaza en el plano de datos** cualquier query cuya PK no empiece por ese tenant— **no tiene traducción en GCP**. En GCP, si tu código tiene la service account de Firestore, puede leer todos los tenants. La barrera es el código, no la plataforma.

#### Lo que sí ofrece GCP, y qué mitiga cada cosa

| Mecanismo | Qué consigue | Qué NO consigue |
|---|---|---|
| **IAM Conditions** con `resource.name.startsWith(...)` | Funciona bien para **Cloud Storage** (prefijos de objeto) y Secret Manager | ❌ No aplica a filas/documentos de Firestore, Bigtable o Spanner |
| **WIF Attribute Conditions** | Mapea claims del token externo a `google.subject` y hasta **50 atributos custom** (`attribute.tenant`), y concede roles a `principalSet://iam.googleapis.com/projects/{N}/locations/global/workloadIdentityPools/{POOL}/attribute.tenant/{VALOR}` | Es el análogo más cercano a **session tags**, pero solo gobierna qué recursos GCP puede tocar la identidad, **no filas dentro de una base de datos** |
| **Service account por tenant** + Firestore **base de datos por tenant** (máx. 100) | Aislamiento real en el plano de datos vía IAM sobre el recurso `database` | Tope de **100 bases de datos/proyecto**; no escala a miles de tenants |
| **Proyecto por tenant** | Aislamiento máximo: IAM, cuotas, facturación, VPC-SC, audit logs separados | Sobrecarga operativa alta; requiere fábrica de proyectos y Terraform generado |
| **Firestore Security Rules** | Útil **solo** si algún cliente accede directamente a Firestore | ❌ Irrelevante para el middleware server-side |
| **VPC Service Controls** | Perímetro de servicio que impide exfiltración entre proyectos | Granularidad de proyecto, no de fila |

#### Mitigación recomendada (defensa en profundidad, tres capas)

1. **Capa de aplicación (obligatoria, la que realmente aplica):** un **único** `TenantScopedRepository` en el núcleo hexagonal por el que pasa *toda* consulta, que inyecta el `tenant_id` en el path/prefijo antes de tocar el adaptador. Ningún otro código puede construir una referencia a Firestore. Refuérzalo con tests de arquitectura (ArchUnit / import-linter) que fallen si algo importa el cliente de Firestore fuera del adaptador.
2. **Capa criptográfica (la que hace fallar de forma segura):** cifrado de sobre por tenant con **Tink** (capacidad 6), usando `tenant_id` como **Associated Data**. Un bug de scoping devuelve entonces un texto cifrado que **no se puede descifrar** con la clave del tenant equivocado. Esta es la mitigación más valiosa: convierte una fuga de datos en un error de descifrado.
3. **Capa de plataforma (para tenants de alto valor):** proyecto dedicado o base de datos Firestore dedicada, con WIF `attribute.tenant` y VPC Service Controls.

Y en todos los casos: **Data Access audit logs habilitados sobre Firestore** con alerta sobre accesos cuyo `tenant_id` en el path no coincida con el del token — detección, ya que no hay prevención.

**Consecuencia para el diseño hexagonal:** el `TenantIsolationPort` es el punto donde AWS y GCP divergen más. En AWS el puerto puede ser casi vacío (la plataforma aplica la política). En GCP el puerto debe contener lógica real. **Escribe el puerto asumiendo el modelo GCP (aplicación explícita) y deja que AWS lo refuerce**, no al revés — si diseñas asumiendo LeadingKeys, el adaptador GCP quedará estructuralmente inseguro.

**Terraform:** `google_project_iam_member` con bloque `condition { expression = "resource.name.startsWith(...)" }` · `google_iam_workload_identity_pool`, `google_iam_workload_identity_pool_provider` (`attribute_mapping`, `attribute_condition`) · `google_service_account`, `google_service_account_iam_member` · `google_access_context_manager_service_perimeter` · `google_firestore_database` (una por tenant) · `google_firebaserules_ruleset` / `_release` (solo si hay acceso desde cliente)

Fuentes: [IAM Conditions overview](https://docs.cloud.google.com/iam/docs/conditions-overview) · [Workload Identity Federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation) · [Firestore Security Rules — get started](https://docs.cloud.google.com/firestore/native/docs/security/get-started)

---

### 8. OCR de documentos de identidad

| Procesador GCP | Cobertura | Precio verificado |
|---|---|---|
| **Enterprise Document OCR** | +200 idiomas, manuscrito, calidad de documento | **$1,50 / 1.000 páginas** (1k–5M); **$0,60 / 1.000** (>5M); **primeras 1.000 páginas gratis** |
| **US Driver License Parser** | 🔴 **Solo los 50 estados de EE. UU. + D.C.** | **$0,10 por count** (1 count = hasta 10 páginas) ≈ **$10 / 1.000 páginas** |
| **US Passport Parser** | 🔴 Solo EE. UU. | Idem |
| **Identity Document Proofing** | Señales de fraude: manipulación de imagen, palabras sospechosas, si contiene un documento reconocido. 🔴 **Solo pasaportes, passcards y licencias de EE. UU.** | Idem |

**Límites operativos:** OCR online máx. **15 páginas**, batch **500 páginas** (más en imageless mode). Procesadores de identidad: hasta **200 páginas** en batch. Regiones: US, EU, Asia-Pacífico. La detección de duplicados online **se procesa en centros de datos de EE. UU.**

**Deprecaciones activas (importante):** `pretrained-us-passport-v1.0-2021-06-14` y `pretrained-fr-driver-license-v1.0-2021-06-14` se apagan el **30 de junio de 2026** — es decir, **ya deberían estar migrados**. Nota que el procesador de licencia de conducir francesa está siendo retirado, lo que refuerza el punto siguiente.

#### 🔴 Brecha real: cobertura geográfica

Textract `AnalyzeID` también está limitado a documentos de EE. UU. (licencias y pasaportes), así que **en este punto concreto AWS y GCP están igual de limitados**. Pero si tu eKYC opera en LATAM, Europa o Asia, **ninguno de los dos procesadores de identidad te sirve** y el patrón real es:

- **Enterprise Document OCR** (o Textract `DetectDocumentText`) para el texto crudo — aquí sí hay paridad razonable y precio comparable.
- **Un LLM multimodal (capacidad 9)** para extraer campos estructurados del documento con un prompt por país/tipo de documento. En 2026 este es el enfoque dominante y es el que mejor se porta entre nubes, porque Claude está disponible en ambas.
- **Un Custom Extractor de Document AI** entrenado con tus propios documentos si el volumen lo justifica.

**No verificado:** precios de Textract `DetectDocumentText` y `AnalyzeID` (no consulté la página de precios de AWS en esta investigación). El precio de HITL de Document AI no aparece en la página de precios — es irrelevante porque el servicio está apagado (ver capacidad 11).

**Advertencias de portabilidad:**
- El **formato de salida difiere por completo**: Textract devuelve `Blocks` (WORD/LINE/PAGE con relaciones), Document AI devuelve un `Document` con `pages[].tokens/lines/paragraphs` y `entities[]`. El `DocumentOcrPort` debe normalizar a un modelo propio con bounding boxes normalizadas (0–1), no exponer ninguno de los dos.
- Los **límites de páginas online** (15 en Document AI) son más restrictivos que Textract síncrono (1 página / 5 MB pero sin límite de páginas equivalente). Diseña el puerto como **asíncrono por defecto**.
- El OCR de Document AI está **regionalizado** (`us`, `eu`, `asia`) y el endpoint va en el nombre del procesador. Para residencia de datos UE, fija la región explícitamente.

**Terraform:** `google_document_ai_processor`, `google_document_ai_processor_default_version`

Fuentes: [Processors list](https://docs.cloud.google.com/document-ai/docs/processors-list) · [Document AI pricing](https://cloud.google.com/products/document-ai/pricing) · [Document AI deprecations](https://docs.cloud.google.com/document-ai/docs/deprecation)

---

### 9. LLM multimodal gestionado con prompt caching

#### ¿Claude está disponible en Vertex AI / Agent Platform? **Sí, y con paridad casi total.**

Modelos disponibles (agosto 2026) con sus IDs en Agent Platform:

| Modelo | ID | Ventana de contexto |
|---|---|---|
| Claude Fable 5 | `claude-fable-5` | 1M tokens |
| Claude Opus 5 | `claude-opus-5` | 1M tokens |
| Claude Sonnet 5 | `claude-sonnet-5` | 1M tokens |
| Claude Opus 4.8 / 4.7 / 4.6 | `claude-opus-4-8` / `-4-7` / `-4-6` | 1M tokens |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | 1M tokens |
| Claude Opus 4.5 | `claude-opus-4-5@20251101` | 200k |
| Claude Sonnet 4.5 | `claude-sonnet-4-5@20250929` | 200k |
| Claude Haiku 4.5 | `claude-haiku-4-5@20251001` | 200k |

- **Endpoints:** global (`region="global"`, recomendado), multi-región (`us`, `eu`), o regional (`us-east5`, `europe-west1`). El **endpoint global de Claude está GA**.
- **Provisioned Throughput disponible** — equivalente a Provisioned Throughput de Bedrock.
- **Zero Data Retention (ZDR)** compatible en Opus 5 — relevante para eKYC.
- **Payload máximo: 30 MB** por petición.

#### Prompt caching de Claude

**Sí, soportado en Agent Platform.** Los mínimos de tokens **son los mismos en todas las plataformas** donde el modelo esté disponible (así lo indica la documentación de Anthropic), por lo que **el porte de Bedrock a GCP no cambia los umbrales**:

| Modelo | Mínimo cacheable |
|---|---|
| Claude Opus 5, Fable 5, Mythos 5 | **512 tokens** |
| Claude Opus 4.8, Sonnet 5, Sonnet 4.6, Sonnet 4.5 | 1.024 |
| Claude Opus 4.7 | 2.048 |
| Claude Opus 4.6, Opus 4.5, Haiku 4.5 | 4.096 |

- **TTL:** 5 min (default, sin coste extra) o **1 h** (`"cache_control": {"type":"ephemeral","ttl":"1h"}`).
- **Máximo 4 cache breakpoints** por petición.
- **Multiplicadores:** escritura 5 min = **1,25×**; escritura 1 h = **2,0×**; lectura = **0,1×**.

#### ¿Vertex AI (Gemini) tiene context caching? **Sí, y los mínimos son distintos a los de Claude.**

| Familia | Mínimo de tokens para caché |
|---|---|
| **Gemini 3.x / 3.1** | **4.096 tokens** |
| **Gemini 2.0 / 2.5** | **2.048 tokens** |

- **Implicit caching**: activado por defecto en todos los proyectos, **descuento del 90 %** sobre tokens cacheados, **sin coste de almacenamiento**. No tiene equivalente en Bedrock (donde el caching es siempre explícito).
- **Explicit caching**: TTL default **60 min**, mínimo **1 min**, sin máximo documentado. Cobra almacenamiento por duración. Descuento del 90 % en Gemini 2.5+ y 75 % en Gemini 2.0.
- Modelos soportados: Gemini 3.1 Flash-Lite, 3.1 Pro (preview), 3 Flash (preview), 2.5 Pro/Flash/Flash-Lite, alias `gemini-flash-latest`.

**Advertencias de portabilidad:**
- 🟢 **Esta es la capacidad que mejor se porta.** Usando Claude en ambas nubes, el `LlmPort` puede ser prácticamente el mismo: la Messages API es idéntica, `cache_control` es idéntico, los mínimos de tokens son idénticos. Las diferencias son de **autenticación** (SigV4 vs. ADC/OAuth2) y de **nombre de modelo** (`anthropic.claude-...-v1:0` en Bedrock vs. `claude-opus-5` en Agent Platform).
- ⚠️ El puerto **no debe exponer `cache_control` de Anthropic directamente** si quieres poder cambiar a Gemini: el modelo de caching de Gemini (recursos `CachedContent` con nombre y TTL) es estructuralmente distinto al de breakpoints en el prompt. Expón `cachearPrefijo(contenido, ttl)` y deja que cada adaptador lo traduzca.
- ⚠️ Activar Claude en Model Garden requiere **aceptar un acuerdo en Marketplace**; **no hay un recurso Terraform que lo haga**. Es un paso manual (o vía API de Marketplace) que debes documentar en el runbook de bootstrap.
- **Cuidado con el rebranding:** las rutas de documentación y los nombres de consola cambiaron a `agent-platform`; la API sigue en `aiplatform.googleapis.com` y Terraform en `google_vertex_ai_*`.

**Terraform:** `google_vertex_ai_endpoint`, `google_vertex_ai_index`, `google_vertex_ai_index_endpoint` · Habilitación de API: `google_project_service` con `aiplatform.googleapis.com` · **Sin recurso TF** para aceptar el modelo de Claude en Model Garden

Fuentes: [Claude en Model Garden](https://cloud.google.com/products/model-garden/claude) · [Claude on Google Cloud (Anthropic)](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai) · [Prompt caching (Anthropic)](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) · [Vertex context caching overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview)

---

### 10. Biometría facial gestionada y liveness

#### Respuesta directa: **GCP NO tiene equivalente. Ni a `CompareFaces`, ni a Face Liveness.**

Cloud Vision API detecta caras (bounding box, landmarks, likelihoods de emoción, headwear), pero la documentación es explícita: **"Specific individual Facial Recognition is not supported."** No hay comparación 1:1, no hay verificación de identidad, no hay detección de vivacidad, no hay antispoofing, no hay presentation attack detection.

Esta es **la brecha más grave de todo el portaje**, porque:
- Rekognition Face Liveness es un servicio **certificado y auditado** (relevante para cumplimiento en muchas jurisdicciones).
- Incluye **SDK de cliente** (React/Swift/Android) con el reto visual (secuencia de colores/oval) — no es solo una API, es un flujo completo cliente-servidor con protección contra replay.
- Devuelve un score de confianza y **una imagen de referencia auditada** que puedes encadenar a `CompareFaces` contra el documento.

#### Alternativas, con evaluación honesta

| Opción | Viabilidad | Riesgo |
|---|---|---|
| **A. Contenedor propio en Cloud Run con InsightFace/ArcFace ONNX** | ✅ Resuelve **`CompareFaces`** muy bien: embeddings + similitud coseno. Cloud Run con L4 GPU hace esto en decenas de ms con cold start ~5 s | 🟡 Medio. Es un problema resuelto y bien documentado |
| **B. Liveness propio (pasivo o activo con reto)** | ⚠️ Resuelve `Face Liveness` **mal**. Los modelos abiertos de antispoofing (Silent-Face-Anti-Spoofing, MiniFASNet) son notoriamente débiles frente a ataques de inyección, deepfakes y máscaras 3D | 🔴 **Alto.** No lo hagas para producción regulada |
| **C. Proveedor SaaS de terceros** (iProov, Incode, Onfido/Entrust, Jumio, FaceTec, Veriff, HyperVerge, Regula) | ✅ Es **la recomendación real**. Muchos ofrecen certificación **iBeta PAD Level 1/2** y disponibilidad multi-nube | 🟢 Bajo, pero añade un tercero al perímetro de datos |
| **D. Mantener Rekognition como servicio cross-cloud** | ✅ Técnicamente posible: llamar a Rekognition desde Cloud Run | 🟡 Contradice el objetivo del portaje; egreso, latencia, y dos cuentas cloud |

**Recomendación para el diseño hexagonal:** define **dos puertos separados**, porque tienen distinta portabilidad:

```
FaceMatchPort   → AWS: Rekognition CompareFaces
                → GCP: Cloud Run + InsightFace ONNX   [portable]

LivenessPort    → AWS: Rekognition Face Liveness
                → GCP: SaaS de terceros                [NO portable]
```

Separarlos importa: `FaceMatchPort` se porta sin drama, `LivenessPort` no. Si los unes en un `BiometricsPort`, arrastras el segundo problema al primero.

**Advertencia crítica:** `LivenessPort` **no es solo un puerto de servidor**. El liveness de Rekognition incluye un SDK de cliente. Portarlo implica **cambiar el frontend**, no solo el backend. El coste del portaje incluye trabajo de app móvil/web que un análisis puramente de infraestructura pasa por alto.

**Terraform:** ninguno específico. `google_cloud_run_v2_service` con GPU (`node_selector { accelerator = "nvidia-l4" }`) para el adaptador de face match; el proveedor SaaS se configura vía `google_secret_manager_secret` para sus credenciales.

Fuentes: [Cloud Vision — detecting faces](https://docs.cloud.google.com/vision/docs/detecting-faces) · [Amazon Rekognition Face Liveness](https://docs.aws.amazon.com/rekognition/latest/dg/face-liveness.html)

---

### 11. Revisión humana en el bucle

#### Estado de SageMaker A2I: **cerrado a nuevos clientes.**

Cita textual de la documentación de AWS: *"Amazon SageMaker A2I is no longer open to new customers. Existing customers can continue to use the service as normal. AWS continues to invest in security and availability improvements for A2I, but we do not plan to introduce new features."*

**Implicación inmediata:** si tu implementación de referencia en AWS usa A2I, **ya estás sobre un servicio en modo mantenimiento**. Y si el proyecto AWS es nuevo, **ni siquiera puedes darte de alta**. Esto invierte la premisa: no es que GCP vaya por detrás, es que **ambas nubes han abandonado el HITL gestionado**.

#### Estado en GCP: **peor — ambos servicios están apagados, no solo deprecados.**

| Servicio | Estado |
|---|---|
| **Document AI Human-in-the-Loop (HITL)** | 🔴 **Apagado.** *"Document AI Human-in-the-Loop is deprecated and will no longer be available on Google Cloud after January 16, 2025."* |
| **Vertex AI Data Labeling Service** | 🔴 **Apagado desde el 3 de octubre de 2024** |

La recomendación oficial de Google para HITL es literalmente **contratar un partner certificado** (menciona Devoteam, Searce, Quantiphi). No hay producto.

#### Alternativa: construirlo

Para eKYC, el HITL es una cola de revisión con UI. La buena noticia es que es el componente **menos dependiente de la nube** de toda la arquitectura, y probablemente ya deberías tenerlo custom (A2I nunca encajó bien en flujos KYC porque su modelo de "worker task template" está pensado para etiquetado de ML, no para decisiones de compliance con trazabilidad regulatoria).

Arquitectura mínima en GCP:
- **Cola de casos:** Firestore (colección `revisiones` con estado, prioridad, asignación) + TTL para expiración de SLA.
- **Disparo:** Workflows con `create_callback_endpoint` (⚠️ recuerda el techo de 12 h) o, mejor para revisión humana con SLA largo, **persistir y relanzar** el workflow.
- **UI de revisión:** Cloud Run + Identity Platform (autenticación de revisores) + IAP si es interno.
- **Auditoría:** Cloud Audit Logs + un log de decisiones inmutable en GCS con **Bucket Lock** (WORM) — esto es lo que A2I nunca dio bien y lo que compliance sí pide.
- **Fuerza de trabajo:** Amazon Mechanical Turk / vendor workforce **no tiene equivalente en GCP**; para eKYC casi siempre es personal interno o un BPO, no crowdsourcing (los datos son PII).

**Consecuencia para el hexágono:** 🟢 **Convierte esto en una oportunidad.** El `HumanReviewPort` debe implementarse como servicio propio en ambas nubes. Es la única capacidad donde la respuesta correcta es "no uses el servicio gestionado de ninguna de las dos", lo que **elimina la asimetría** en lugar de gestionarla.

**Terraform:** `google_firestore_database`, `google_cloud_run_v2_service`, `google_identity_platform_tenant`, `google_storage_bucket` con `retention_policy { is_locked = true }`, `google_iap_settings`

Fuentes: [A2I human review loops](https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-use-augmented-ai-a2i-human-review-loops.html) · [Document AI HITL deprecation](https://docs.cloud.google.com/document-ai/docs/hitl) · [Vertex AI deprecations](https://docs.cloud.google.com/vertex-ai/docs/deprecations)

---

### 12. Observabilidad y auditoría

| AWS | GCP | Diferencias relevantes |
|---|---|---|
| CloudWatch Logs | **Cloud Logging** | Log entry **256 KiB** (audit: 512 KiB) vs. CloudWatch 256 KB — paridad |
| CloudWatch Metrics/Alarms | **Cloud Monitoring** | Modelo de métricas distinto (métricas basadas en recurso, no en dimensión libre) |
| X-Ray | **Cloud Trace** | Cloud Trace usa **OpenTelemetry / Cloud Trace API**; X-Ray usa su propio SDK. **OTel es el denominador común: instrumenta con OTel en ambas** |
| CloudTrail | **Cloud Audit Logs** | Ver tabla abajo |

**Tipos de Cloud Audit Logs:**

| Tipo | Por defecto | Coste | Equivalente AWS |
|---|---|---|---|
| **Admin Activity** | ✅ Siempre escrito, **no se puede desactivar** | Gratis | CloudTrail management events |
| **Data Access** | 🔴 **Deshabilitado por defecto** (excepto BigQuery) | De pago | CloudTrail data events |
| **System Event** | ✅ Siempre escrito, no desactivable | Gratis | — |
| **Policy Denied** | ✅ Generado por defecto, excluible por filtro | De pago | — |

**Retención de logs:**

| Bucket | Retención | Configurable |
|---|---|---|
| `_Required` (Admin Activity, System Event, Policy Denied) | **400 días** | ❌ No |
| `_Default` (proyectos) | 30 días | ✅ **1–3.650 días** |
| `_Default` (carpetas/organizaciones) | 30 días | ❌ No |
| Buckets definidos por el usuario | — | ✅ 1–3.650 días |

**Advertencias de portabilidad:**
- 🔴 **Data Access logs están apagados por defecto.** Para eKYC esto es un fallo de cumplimiento silencioso: si no los habilitas explícitamente sobre Firestore, GCS y KMS, **no tienes traza de quién leyó datos de qué tenant**. En AWS, CloudTrail data events también están apagados por defecto, así que hay paridad — pero es fácil olvidarlo al portar. **Habilítalos en el Terraform base con `google_project_iam_audit_config`.**
- 🟢 Los 400 días de retención de `_Required` **superan** a CloudTrail (90 días de event history; más requiere un trail a S3).
- ⚠️ El coste de Data Access logs sobre Firestore en un middleware de alto volumen puede ser significativo. Usa **exclusion filters** para reducir ruido, pero nunca excluyas accesos a datos de tenant.
- Cloud Trace no tiene equivalente exacto al **service map** de X-Ray ni a X-Ray Insights.

**Terraform:** `google_logging_project_sink`, `google_logging_project_bucket_config`, `google_logging_metric`, `google_logging_project_exclusion` · `google_project_iam_audit_config` (crítico: habilita Data Access) · `google_monitoring_alert_policy`, `google_monitoring_notification_channel`, `google_monitoring_dashboard`, `google_monitoring_uptime_check_config` · Cloud Trace: sin recurso propio, habilitar `cloudtrace.googleapis.com` con `google_project_service`

Fuentes: [Cloud Audit Logs overview](https://docs.cloud.google.com/logging/docs/audit) · [Logging quotas and limits](https://docs.cloud.google.com/logging/quotas)

---

### 13. Secretos y configuración

**Secret Manager cubre Secrets Manager, pero NO hay equivalente a Parameter Store.**

| Límite verificado | Valor |
|---|---|
| Payload por versión | **64 KiB** |
| Alias por secreto | 50 |
| `AddSecretVersion`/`UpdateSecret` — global | 2 qps por secreto, 120/min |
| `AddSecretVersion`/`UpdateSecret` — regional | 80 qps por secreto/región, 4.800/min |
| Enable/Disable/Destroy — global | 1 qps por versión, 60/min |
| Enable/Disable/Destroy — regional | 50 qps por versión/región, 3.000/min |
| `AccessSecretVersion` (proyecto) | 90.000/min |
| Lecturas / escrituras (proyecto) | 600/min cada una |

**No verificado:** máximo de secretos por proyecto y máximo de versiones por secreto (la página de cuotas no los indica).

**Diferencias funcionales:**
- 🔴 **No hay Parameter Store.** AWS separa secretos (Secrets Manager, de pago, con rotación) de configuración (Parameter Store, tier estándar gratis). En GCP **todo va a Secret Manager y todo se cobra**, o usas variables de entorno de Cloud Run / un objeto de configuración en GCS / Firestore. Para configuración no sensible y de alto volumen de lectura, **el límite de 600 lecturas/min a nivel de proyecto es un cuello de botella real** — no uses Secret Manager como almacén de config.
- 🔴 **La rotación no es gestionada como en AWS.** Secrets Manager de AWS rota credenciales de RDS/Redshift/DocumentDB automáticamente con una Lambda de rotación provista. Secret Manager de GCP solo tiene **notificaciones de rotación** vía Pub/Sub (`rotation` + `topics`): tú escribes el rotador. Diferencia significativa de esfuerzo.
- 🟢 Secret Manager tiene **secretos regionales** (`google_secret_manager_regional_secret`) además de globales con réplica automática — útil para residencia de datos UE.
- 🟢 Integración nativa con Cloud Run: montaje como volumen o variable de entorno, con `latest` o versión fija. **Fija la versión** en producción; `latest` provoca cambios no auditados.

**Advertencias de portabilidad:**
- El `ConfigPort` debe separarse del `SecretPort`. En AWS ambos tienen backend gestionado; en GCP el `ConfigPort` no lo tiene y su implementación natural es "variables de entorno inyectadas por Terraform" o un documento de config en Firestore con caché en proceso.
- El límite de **64 KiB** iguala al de AWS Secrets Manager (65.536 bytes). Sin sorpresas.

**Terraform:** `google_secret_manager_secret` (bloques `replication`, `rotation`, `topics`), `google_secret_manager_secret_version`, `google_secret_manager_secret_iam_member`, `google_secret_manager_regional_secret`, `google_secret_manager_regional_secret_version`

Fuentes: [Secret Manager quotas and limits](https://docs.cloud.google.com/secret-manager/quotas)

---

### 14. Registro de contenedores

**Paridad alta, con ventaja para GCP.**

| Límite verificado (Artifact Registry) | Valor |
|---|---|
| Peticiones por proyecto | 60.000/min por región |
| Escrituras / borrados | 18.000/min cada uno |
| Borrados por política de limpieza | 300.000 por repo/día |
| Políticas de limpieza | 10 por repositorio |
| Recuperación desde upstream | 9,9 GB por petición |
| Políticas upstream en repos virtuales | 30 |
| Operaciones de creación/borrado de repos | 30/región/min |
| Listado de artefactos | 10.000 por repositorio |
| Lecturas desde Docker Hub (remote repo) | 600/organización/región/min |

**No verificado:** máximo de repositorios por proyecto, límite de tamaño de imagen/capa, y almacenamiento del free tier.

**Ventajas de Artifact Registry sobre ECR:**
- 🟢 **Multi-formato en un solo servicio:** Docker/OCI, Maven, npm, Python, Go, apt, yum, Helm. ECR es solo OCI (ECR Public aparte).
- 🟢 **Remote repositories** (proxy con caché de Docker Hub, PyPI, Maven Central, npm) y **virtual repositories** (agregación). ECR tiene pull-through cache, más limitado.
- 🟢 **Cleanup policies** declarativas (equivalente a lifecycle policies de ECR, con paridad).
- 🟢 Escaneo de vulnerabilidades vía **Artifact Analysis**; ECR usa Inspector.
- 🟢 CMEK soportado, y **Autokey lo soporta**.

**Advertencias de portabilidad:**
- La **autenticación difiere**: ECR usa `aws ecr get-login-password` (token de 12 h); Artifact Registry usa `gcloud auth configure-docker` con credential helper o una service account key. En CI, usa **Workload Identity Federation** desde GitHub Actions/GitLab en lugar de claves.
- El **naming** cambia: `<acct>.dkr.ecr.<region>.amazonaws.com/<repo>:<tag>` vs. `<region>-docker.pkg.dev/<project>/<repo>/<image>:<tag>`. El nivel extra de jerarquía (repo → image) no existe en ECR. Parametriza la URI de imagen en el módulo Terraform de despliegue, no la construyas en el código.
- **Binary Authorization** (`google_binary_authorization_policy`) permite exigir imágenes firmadas y atestadas antes de desplegar en Cloud Run — es más maduro que el equivalente en AWS y vale la pena adoptarlo para un middleware de eKYC.

**Terraform:** `google_artifact_registry_repository` (incluye `cleanup_policy`, `remote_repository_config`, `virtual_repository_config`, `kms_key_name`), `google_artifact_registry_repository_iam_member` · `google_binary_authorization_policy`, `google_binary_authorization_attestor`

Fuentes: [Artifact Registry quotas and limits](https://docs.cloud.google.com/artifact-registry/quotas)

---

### 15. Red privada y egreso controlado

| AWS | GCP | Nota |
|---|---|---|
| VPC, subredes | VPC (**global**), subredes (regionales) | 🟢 La VPC de GCP es global; simplifica el multi-región |
| VPC Endpoint (Gateway/Interface) | **Private Service Connect endpoint para Google APIs** | Permite usar **tus propias IPs internas** para alcanzar `storage.googleapis.com`, etc. |
| PrivateLink (publicar servicio) | **PSC published service** + **service attachment** | Un service attachment apunta a un LB del productor y define la lista de consumidores aceptados y la subred NAT |
| Lambda en VPC (ENIs) | **Direct VPC egress** o **Serverless VPC Access connector** | Ver abajo |
| NAT Gateway | **Cloud NAT** | |
| Security Groups + NACLs | **Firewall rules** + **Firewall Policies** (etiquetas y cuentas de servicio como selectores) | Modelo distinto: GCP no tiene el concepto de SG como referencia mutua |
| — | **VPC Service Controls** | 🟢 **Sin equivalente en AWS.** Perímetro que impide exfiltración de datos desde servicios gestionados. Muy valioso para eKYC |

**Direct VPC egress vs. Serverless VPC Access connector:**

| | Connector | Direct VPC egress |
|---|---|---|
| Infraestructura | VMs gestionadas que pagas siempre | Sin recurso intermedio, **escala a cero** |
| Coste | Fijo por instancia del conector | Solo tráfico |
| Instancias máx. | Mayor | 🔴 **100–200 según región** |
| Subred | Dedicada `/28` | **`/26` o mayor** |
| Throughput | Según tamaño del conector | Hasta **1 Gbps por instancia** |
| Ingress privado | No | Solo **worker pools** (services y jobs no) |

**Advertencias de portabilidad:**
- 🔴 **El límite de 100–200 instancias con Direct VPC egress** es el que más probablemente te muerda. Si el middleware necesita escalar a más y también necesita acceso privado, tendrás que usar connectors (coste fijo) o repartir en varios servicios.
- ⚠️ **Retrasos de establecimiento de conexión de un minuto o más en el arranque de instancia**, y **cold starts de 30 s o más con Cloud NAT**. Esto es materialmente peor que Lambda-en-VPC tras las mejoras de Hyperplane de AWS. Para APIs sincrónas de eKYC con SLA de latencia, **mide esto antes de comprometerte**.
- ⚠️ **Los jobs de Cloud Run que superen 1 hora pueden sufrir cortes de conexión** durante eventos de mantenimiento. Diseña los jobs largos con reintentos idempotentes.
- **Dimensionado de subred:** en estado estable, los services consumen **2× las IPs de las instancias en ejecución**; los jobs, una IP por tarea más 7 minutos de retención tras completarse. Un `/26` (64 IPs) soporta ~30 instancias. **Sobredimensiona.**
- **VPC Service Controls es la pieza que no existe en AWS** y que deberías adoptar en el diseño GCP: define un perímetro que contenga Firestore, GCS, KMS y Document AI, de modo que ninguna credencial robada pueda exfiltrar datos fuera del perímetro. **Esto compensa parcialmente la brecha de LeadingKeys** (capacidad 7) a nivel de proyecto.

**Terraform:** `google_compute_network`, `google_compute_subnetwork`, `google_compute_firewall`, `google_compute_network_firewall_policy` · `google_vpc_access_connector` · Direct VPC egress: bloque `vpc_access { network_interfaces {} , egress = "ALL_TRAFFIC" }` dentro de `google_cloud_run_v2_service` · `google_compute_service_attachment` (publicar), `google_compute_forwarding_rule` con `target = <service attachment>` (consumir) · `google_compute_router`, `google_compute_router_nat` · `google_compute_global_address` + `google_service_networking_connection` · `google_access_context_manager_service_perimeter`, `google_access_context_manager_access_policy`

Fuentes: [Private Service Connect](https://docs.cloud.google.com/vpc/docs/private-service-connect) · [Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)

---

## 3. Brechas críticas de paridad

Ordenadas por impacto en el diseño hexagonal.

### 🔴 Brecha 1 — Liveness facial gestionado (capacidad 10)

**No existe en GCP.** Cloud Vision declara explícitamente que no soporta reconocimiento facial individual. No hay antispoofing, no hay reto de vivacidad, no hay SDK de cliente.

**Implicación para el hexágono:**
- Separa `FaceMatchPort` (portable con InsightFace/ONNX en Cloud Run + L4) de `LivenessPort` (no portable).
- `LivenessPort` **no es un puerto puramente de backend**: su implementación en AWS incluye un SDK de cliente. Un adaptador GCP requiere cambiar el frontend. **Presupuesta trabajo de app móvil/web, no solo de infraestructura.**
- La implementación GCP realista es un **tercero SaaS** (con certificación iBeta PAD). Eso significa que el `LivenessPort` acaba teniendo **tres** adaptadores, no dos: AWS, SaaS, y potencialmente el mismo SaaS también en AWS — lo que sugiere que **quizá deberías usar el SaaS en ambas nubes** y eliminar la asimetría de raíz.
- Riesgo regulatorio: no construyas liveness propio con modelos abiertos para un flujo KYC en producción.

### 🔴 Brecha 2 — `dynamodb:LeadingKeys` / aislamiento multi-tenant en el plano de datos (capacidad 7)

**No existe en GCP, en ninguna forma.** IAM Conditions no expone atributos de clave de fila/documento. Las Security Rules de Firestore son **irrelevantes** para un backend porque *"the server client libraries bypass all Firestore Security Rules."*

**Implicación para el hexágono:**
- Esta es la brecha más peligrosa porque es **silenciosa**: el código funciona, simplemente no está aislado.
- **Invierte la dirección del diseño.** Si escribes el `TenantIsolationPort` asumiendo que la plataforma aplica la política (modelo AWS), el adaptador GCP quedará estructuralmente inseguro. Diseña asumiendo el modelo GCP —aplicación explícita en un único repositorio con scope de tenant— y deja que el adaptador AWS añada `LeadingKeys` como refuerzo redundante.
- La mitigación que realmente convierte un bug en un fallo seguro es **criptográfica**: cifrado de sobre por tenant con Tink usando `tenant_id` como Associated Data (capacidad 6). Un error de scoping produce entonces un fallo de descifrado, no una fuga.
- Complementa con: **base de datos Firestore por tenant** (tope 100) o **proyecto por tenant** para clientes de alto valor, WIF con `attribute.tenant`, **VPC Service Controls** como perímetro, y **Data Access audit logs** con alertas de desalineación tenant/token.
- Tests de arquitectura automatizados que fallen si el cliente de Firestore se importa fuera del adaptador.

### 🔴 Brecha 3 — Human-in-the-loop gestionado (capacidad 11)

**Ambas nubes lo han abandonado.** A2I está *"no longer open to new customers"*; Document AI HITL **se apagó el 16 de enero de 2025**; Vertex AI Data Labeling **se apagó el 3 de octubre de 2024**. La recomendación oficial de Google es contratar un partner.

**Implicación para el hexágono:**
- 🟢 **Paradójicamente, esto simplifica el diseño.** El `HumanReviewPort` debe implementarse como servicio propio en **ambas** nubes (Firestore/DynamoDB + Cloud Run/Lambda + UI + log WORM). La asimetría desaparece.
- Si tu implementación AWS actual usa A2I, **ya tienes deuda técnica independientemente del portaje** — trátalo como refactor prioritario, no como coste del porte.
- Ventaja de construirlo: A2I nunca dio bien la trazabilidad regulatoria (worker task templates pensados para etiquetado ML, no para decisiones de compliance). Un servicio propio con **GCS Bucket Lock** o **S3 Object Lock** para el log de decisiones cumple mejor.

### 🟡 Brecha 4 — AWS Database Encryption SDK (capacidad 6)

**No existe equivalente.** Tink cubre el cifrado de sobre y el AAD, pero **no** la firma del registro completo, ni los atributos firmados-pero-no-cifrados, ni los **searchable encryption beacons** (consultas de igualdad sobre campos cifrados).

**Implicación:**
- Si tu diseño AWS consulta por campos cifrados usando beacons, **ese patrón no se porta**. Tendrás que rediseñar: índice separado con hash HMAC determinista con clave por tenant (esencialmente reimplementar beacons), asumiendo tú el análisis de fuga de frecuencia.
- Tink **no tiene caching de material criptográfico integrado**; debes implementarlo o la latencia de KMS por operación hará inviable el sistema ([issue #697](https://github.com/google/tink/issues/697)).
- 🔴 **Tink no tiene versión JavaScript/TypeScript mantenida.** Si el middleware es Node.js, esto es un bloqueante: sidecar en Go/Java, o implementar el envelope directamente contra la API de Cloud KMS.
- Crypto-shredding: Cloud KMS **no permite destrucción inmediata**; default 30 días, configurable. **No pude verificar el mínimo configurable** — verifícalo antes de comprometer un SLA de borrado.

### 🟡 Brecha 5 — Lambda Authorizer (capacidad 1)

GCP API Gateway solo soporta autenticación declarativa (API keys, JWT contra emisores configurados, service accounts). **No hay ejecución de código arbitrario por petición en el gateway.**

**Implicación:**
- Mueve la lógica de autorización al **middleware in-process de Cloud Run**. Esto es en realidad **más portable**, no menos: saca la autorización del adaptador de infraestructura y la lleva al núcleo.
- Pierdes el **caché de authorizer** de API Gateway (hasta 3600 s). Implementa caché en proceso con TTL.
- Si necesitas gobernanza real de API con políticas custom, la respuesta es **Apigee**, con un salto de coste considerable.

### 🟡 Brecha 6 — Semántica de streams y patrón single-table (capacidad 4)

Firestore + Eventarc **no garantiza orden** y **no permite replay** del stream. DynamoDB Streams garantiza orden por clave de partición y retiene 24 h con reproceso.

**Implicación:**
- Si tu saga de onboarding depende del orden de los eventos por caso, **necesitas ordenación explícita** (número de secuencia en el documento + reordenación en el consumidor) o Pub/Sub con **ordering keys**.
- Sin replay: para reprocesar, itera la colección, no el stream. Diseña los consumidores como **idempotentes y reentrantes** desde el principio.
- **Single-table no se emula bien en Firestore.** Si el modelo es agresivamente single-table, el destino correcto es **Bigtable** (row keys ordenadas, prefijos) o **Spanner** (el único con change streams reales: orden garantizado y replay de 7 días). Reconoce esto pronto: elegir Firestore por reflejo "NoSQL → NoSQL" y luego descubrir que las consultas de rango sobre sort key no existen es un fallo caro.
- El **puerto de repositorio debe exponer operaciones de dominio**, no primitivas PK/SK. Si tu puerto actual acepta `begins_with`, ya está acoplado a DynamoDB.

### 🟡 Brecha 7 — `waitForTaskToken` con horizonte largo (capacidad 2)

Los callbacks de Cloud Workflows tienen **default de 12 h**, **un solo slot pendiente por endpoint** (HTTP 429 al segundo), y **sin heartbeat**. Step Functions permite hasta 1 año, tokens ilimitados y `SendTaskHeartbeat`.

**Implicación:**
- Un flujo de revisión manual que cruce un fin de semana o escale a compliance **no cabe en 12 h**. **No pude verificar un máximo documentado superior**; verifícalo antes de diseñar.
- Patrón alternativo para esperas largas: **persistir el estado en Firestore, terminar el workflow, y lanzar una ejecución nueva** con `executions.run` cuando llegue la decisión. Es menos elegante pero no tiene techo.
- El límite de **512 KB de datos acumulados por ejecución** de Workflows es el más restrictivo de todos: pasa **punteros a GCS**, nunca payloads.

### 🟡 Brecha 8 — Cobertura de documentos de identidad no estadounidenses (capacidad 8)

Los procesadores de identidad de Document AI cubren **solo EE. UU.** (licencias de los 50 estados + D.C., pasaportes, proofing). Y hay deprecaciones activas con apagado el **30 de junio de 2026** (incluida la licencia de conducir francesa).

**Implicación:**
- AWS `AnalyzeID` está igual de limitado a EE. UU., así que **hay paridad en la limitación** — pero si operas fuera de EE. UU., **ninguno de los dos te sirve**.
- El patrón portable es: **OCR genérico** (Enterprise Document OCR / `DetectDocumentText`, precios comparables) + **LLM multimodal** (Claude, disponible en ambas nubes) para extracción estructurada por país. Este enfoque **elimina la brecha** porque el componente diferenciador (Claude) tiene paridad total.

### ⚪ Brecha 9 — Parameter Store (capacidad 13)

GCP no separa configuración de secretos. Todo va a Secret Manager, todo se cobra, y el límite de **600 lecturas/min por proyecto** lo hace inadecuado como almacén de configuración de alto volumen. Además, **la rotación automática de credenciales no es gestionada** (solo notificaciones Pub/Sub; el rotador lo escribes tú).

**Implicación:** separa `ConfigPort` de `SecretPort`. En GCP el `ConfigPort` se implementa con variables de entorno inyectadas por Terraform o un documento de config con caché en proceso.

---

## 4. Recomendaciones de diseño hexagonal

1. **Puertos que se portan sin fricción** (define la interfaz libremente): `ObjectStoragePort`, `LlmPort`, `ContainerRegistry`, `ObservabilityPort`, `PrivateNetworkPort`.
2. **Puertos donde GCP debe dictar la forma de la interfaz** (si AWS la dicta, el adaptador GCP queda inseguro o inviable): `TenantIsolationPort`, `RepositoryPort` (sin primitivas PK/SK), `AuthorizationPort` (lógica en el núcleo, no en el gateway), `SagaPort` (sin dependencia de esperas > 12 h en un solo callback).
3. **Puertos que deben construirse a medida en ambas nubes** (elimina la asimetría en lugar de gestionarla): `HumanReviewPort`, `LivenessPort` (vía SaaS único), `ConfigPort`.
4. **La capa criptográfica es la red de seguridad del multi-tenancy.** Dado que GCP no puede aplicar aislamiento en el plano de datos, el cifrado de sobre por tenant con `tenant_id` como AAD es lo que convierte un bug de scoping en un fallo seguro. Trátalo como requisito, no como defensa en profundidad opcional.

---

## 5. Puntos que NO pude verificar

Los enumero explícitamente para que no se tomen como confirmados:

- **Máximo del parámetro `timeout` de `events.await_callback`** por encima del default de 43.200 s (12 h). La página de callbacks indica que es configurable pero no documenta un techo.
- **Valor mínimo configurable de `destroy_scheduled_duration`** en Cloud KMS (comúnmente citado como 24 h; la documentación de destroy/restore no lo indica).
- **Contradicción documental en Cloud Run:** el máximo de memoria por instancia es 32 GiB, pero la GPU RTX PRO 6000 Blackwell exige un mínimo de 80 GiB. No pude reconciliarlo.
- **Máximo de secretos por proyecto y máximo de versiones por secreto** en Secret Manager.
- **Máximo de repositorios por proyecto, límite de tamaño de imagen/capa, y free tier de almacenamiento** en Artifact Registry.
- **Precios de AWS Textract** (`DetectDocumentText`, `AnalyzeID`) — no consulté la página de precios de AWS.
- **Precios por GB/mes de las clases de Cloud Storage** — la página de clases de almacenamiento no los incluye.
- **Precio de human review de Document AI** — no aparece en la página de precios (irrelevante: el servicio está apagado).
- **Timeout de petición de GCP API Gateway** — no documentado en la página de cuotas.
- **Regiones soportadas por GCP API Gateway** y su estado de desarrollo activo vs. mantenimiento — no confirmado oficialmente.

---

## Fuentes

**Google Cloud — Workflows y orquestación**
- [Workflows quotas and limits](https://docs.cloud.google.com/workflows/quotas)
- [Wait using callbacks | Workflows](https://docs.cloud.google.com/workflows/docs/creating-callback-endpoints)
- [Cloud Tasks quotas](https://docs.cloud.google.com/tasks/docs/quotas)
- [Create HTTP target tasks | Cloud Tasks](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks)
- [Pub/Sub quotas and limits](https://docs.cloud.google.com/pubsub/quotas)

**Google Cloud — Cómputo**
- [Cloud Run quotas and limits](https://docs.cloud.google.com/run/quotas)
- [Configure memory limits for services | Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/memory-limits)
- [GPU support for services | Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/gpu)
- [Cloud Run functions quotas](https://docs.cloud.google.com/functions/quotas)

**Google Cloud — Datos y almacenamiento**
- [Firestore TTL policies](https://docs.cloud.google.com/firestore/native/docs/ttl)
- [Firestore quotas and limits](https://docs.cloud.google.com/firestore/native/docs/quotas)
- [Event-driven architectures with Eventarc | Firestore](https://docs.cloud.google.com/firestore/native/docs/eventarc)
- [Event-driven architectures with Eventarc | Datastore](https://docs.cloud.google.com/datastore/docs/eventarc)
- [Firestore extends triggering support to include Datastore Mode](https://cloud.google.com/blog/products/databases/firestore-extends-triggering-support-to-include-datastore-mode/)
- [Object Lifecycle Management | Cloud Storage](https://docs.cloud.google.com/storage/docs/lifecycle)
- [Storage classes | Cloud Storage](https://docs.cloud.google.com/storage/docs/storage-classes)

**Google Cloud — Seguridad, claves e identidad**
- [Destroy and restore key versions | Cloud KMS](https://docs.cloud.google.com/kms/docs/destroy-restore)
- [Control key version destruction | Cloud KMS](https://docs.cloud.google.com/kms/docs/control-key-destruction)
- [Key version states | Cloud KMS](https://docs.cloud.google.com/kms/docs/key-states)
- [Client-side encryption with Tink and Cloud KMS](https://docs.cloud.google.com/kms/docs/client-side-encryption)
- [Envelope encryption | Cloud KMS](https://docs.cloud.google.com/kms/docs/envelope-encryption)
- [Autokey overview | Cloud KMS](https://docs.cloud.google.com/kms/docs/autokey-overview)
- [Tink issue #697 — Envelope AEAD performance with GCP KMS](https://github.com/google/tink/issues/697)
- [IAM Conditions overview](https://docs.cloud.google.com/iam/docs/conditions-overview)
- [Workload Identity Federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation)
- [Firestore Security Rules — get started](https://docs.cloud.google.com/firestore/native/docs/security/get-started)
- [Secret Manager quotas and limits](https://docs.cloud.google.com/secret-manager/quotas)

**Google Cloud — API y red**
- [API Gateway quotas and limits](https://docs.cloud.google.com/api-gateway/docs/quotas)
- [API Gateway authentication methods](https://docs.cloud.google.com/api-gateway/docs/authentication-method)
- [About API Gateway](https://docs.cloud.google.com/api-gateway/docs/about-api-gateway)
- [Identity Platform multi-tenancy](https://docs.cloud.google.com/identity-platform/docs/multi-tenancy)
- [Identity Platform quotas and limits](https://docs.cloud.google.com/identity-platform/quotas)
- [Private Service Connect](https://docs.cloud.google.com/vpc/docs/private-service-connect)
- [Direct VPC egress | Cloud Run](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)

**Google Cloud — IA y documentos**
- [Document AI processors list](https://docs.cloud.google.com/document-ai/docs/processors-list)
- [Document AI pricing](https://cloud.google.com/products/document-ai/pricing)
- [Document AI deprecations](https://docs.cloud.google.com/document-ai/docs/deprecation)
- [Document AI Human-in-the-Loop deprecation](https://docs.cloud.google.com/document-ai/docs/hitl)
- [Vertex AI deprecations](https://docs.cloud.google.com/vertex-ai/docs/deprecations)
- [Claude en Model Garden](https://cloud.google.com/products/model-garden/claude)
- [Gemini Enterprise Agent Platform (formerly Vertex AI)](https://cloud.google.com/products/gemini-enterprise-agent-platform)
- [Vertex AI context caching overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview)
- [Cloud Vision — detecting faces](https://docs.cloud.google.com/vision/docs/detecting-faces)

**Google Cloud — Observabilidad y artefactos**
- [Cloud Audit Logs overview](https://docs.cloud.google.com/logging/docs/audit)
- [Cloud Logging quotas and limits](https://docs.cloud.google.com/logging/quotas)
- [Artifact Registry quotas and limits](https://docs.cloud.google.com/artifact-registry/quotas)

**Anthropic**
- [Claude on Google Cloud (Vertex AI)](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai)
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

**AWS**
- [Using Amazon Augmented AI for Human Review](https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-use-augmented-ai-a2i-human-review-loops.html)
- [Detecting face liveness | Amazon Rekognition](https://docs.aws.amazon.com/rekognition/latest/dg/face-liveness.html)

**Terraform Registry**
- [google_document_ai_processor](https://library.tf/providers/hashicorp/google/latest/docs/resources/document_ai_processor)
- [google_kms_autokey_config](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/kms_autokey_config)
- [google_identity_platform_tenant](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/identity_platform_tenant)
- [google_identity_platform_config](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/identity_platform_config)

agentId: a0068fc338dc27a6a (use SendMessage with to: 'a0068fc338dc27a6a', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 118308
tool_uses: 60
duration_ms: 1395292</usage>